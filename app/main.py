import os
import pandas as pd
import faiss
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client, Client
from dotenv import load_dotenv
import google.generativeai as genai
from sentence_transformers import SentenceTransformer

# 1. KHỞI TẠO HỆ THỐNG
load_dotenv(override=True)
supabase: Client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

safety_settings = [
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_ONLY_HIGH"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_ONLY_HIGH"},
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_ONLY_HIGH"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_ONLY_HIGH"},
]
llm_model = genai.GenerativeModel('gemini-2.5-flash', safety_settings=safety_settings)

# Tải FAISS và Data
embed_model = SentenceTransformer('all-MiniLM-L6-v2')
index = faiss.read_index("data/webmd_full_vectors.index")
df_clean = pd.read_csv("data/webmd_cleaned.csv")
if 'ThongTinDayDu' not in df_clean.columns:
    df_clean = df_clean.fillna("")
    df_clean['ThongTinDayDu'] = "Đánh giá: " + df_clean['Reviews'].astype(str) + " | Tác dụng phụ: " + df_clean['Sides'].astype(str)

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

class ChatRequest(BaseModel):
    session_id: str
    user_message: str

@app.post("/api/chat")
async def chat_with_pharmacist(request: ChatRequest):
    try:
        supabase.table("users").upsert({"session_id": request.session_id}, on_conflict="session_id").execute()

        # 2. KHÔI PHỤC TRÍ NHỚ (Lấy 5 câu chat gần nhất)
        history_res = supabase.table("chat_history").select("user_message, bot_response").eq("session_id", request.session_id).execute()
        history_text = "\n".join([f"Bệnh nhân: {c['user_message']}\nAI: {c['bot_response']}" for c in (history_res.data[-5:] if history_res.data else [])])
        if not history_text: history_text = "(Chưa có lịch sử, đây là câu đầu tiên)"

        # 3. QUÉT FAISS (Giữ lại thuật toán Vector gốc)
        query_vector = embed_model.encode([request.user_message]).astype('float32')
        distances, indices = index.search(query_vector, k=3)
        raw_docs = df_clean.iloc[indices[0]]['ThongTinDayDu'].tolist()
        thuoc_tuong_ung = df_clean.iloc[indices[0]]['Drug'].tolist()

        # THÊM DÒNG NÀY ĐỂ IN RA MÀN HÌNH ĐEN XEM FAISS TÌM ĐƯỢC GÌ:
        print("\n" + "-"*40)
        print(f" TỪ KHÓA BỆNH NHÂN: {request.user_message}")
        print(f" WEBMD TÌM ĐƯỢC: {thuoc_tuong_ung}")
        print("-" * 40 + "\n")
        # 4. PROMPT TỐI THƯỢNG (Xóa bỏ hoàn toàn form cứng nhắc)
        prompt = f"""
        Bạn là một Trợ lý Bác sĩ/Dược sĩ ảo thông minh, nói chuyện thân thiện như con người.
        
        [Lịch sử trò chuyện trước đó]: {history_text}
        [Câu hỏi hiện tại]: "{request.user_message}"
        [Gợi ý từ FAISS]: {thuoc_tuong_ung} (Chi tiết: {raw_docs})

        NGUYÊN TẮC BẮT BUỘC:
        1. Đọc Lịch sử trò chuyện để hiểu ngữ cảnh.
        2. QUAN TRỌNG NHẤT: FAISS thường quét rất ngớ ngẩn (VD: bệnh nhân hỏi viêm ruột/Bio Acimin thì nó đưa Aspirin). Bạn PHẢI NHẬN DIỆN SỰ SAI LỆCH NÀY. Nếu FAISS đưa thuốc sai/không liên quan, hãy LỜ ĐI HOÀN TOÀN dữ liệu FAISS.
        3. Tự dùng kiến thức y khoa uyên bác của bạn để tư vấn đúng sản phẩm bệnh nhân cần (VD: Bio Acimin, men vi sinh, Oresol, Vitamin...).
        4. KHÔNG BAO GIỜ được in ra cái form "Điểm hiệu quả: 4/5, Điểm dễ sử dụng: 4/5" nữa. Trả lời bằng đoạn văn tự nhiên, thân thiện.
        5. Kết thúc bằng câu dặn dò đi khám bác sĩ nhẹ nhàng.
        """
        # --- VÒNG LẶP HACK GIỚI HẠN API (TỰ ĐỘNG CHUYỂN KEY) ---
        import random
        api_keys = [
            os.getenv("GEMINI_API_KEY"),
            os.getenv("GEMINI_API_KEY_1"),
            os.getenv("GEMINI_API_KEY_2")
        ]
        api_keys = [k for k in api_keys if k] # Xóa key rỗng
        random.shuffle(api_keys) # Xáo trộn danh sách để chia đều tải
        
        bot_reply = ""
        
        # Thử lần lượt từng Key trong danh sách
        for key in api_keys:
            try:
                genai.configure(api_key=key)
                llm_model = genai.GenerativeModel('gemini-2.5-flash', safety_settings=safety_settings)
                
                # Gọi API
                response = llm_model.generate_content(prompt)
                bot_reply = response.text
                
                # NẾU TRẢ LỜI THÀNH CÔNG -> THOÁT VÒNG LẶP LUÔN
                break 
                
            except Exception as e:
                error_msg = str(e)
                if "429" in error_msg or "Quota" in error_msg:
                    # Nếu Key này bị quá tải, in log ra màn hình đen rồi VÒNG LẠI thử Key tiếp theo
                    print(f" Key kết thúc bằng ...{key[-4:]} bị quá tải. Đang tự động đổi Key khác...")
                    continue 
                else:
                    # Nếu lỗi vì từ khóa nhạy cảm, báo lỗi luôn không thử nữa
                    print(f" LỖI TỪ KHÓA NHẠY CẢM: {error_msg}")
                    bot_reply = " Máy chủ AI đang bận hoặc câu hỏi chứa từ khóa nhạy cảm."
                    break

        # Nếu chạy hết cả 3 Key mà bot_reply vẫn rỗng (tức là cả 3 đều hết hạn mức)
        if not bot_reply:
            bot_reply = " Tất cả các Key AI đều đang quá tải. Bạn vui lòng chờ 1 phút nhé!"
        # --------------------------------------------------------
        # 6. LƯU LỊCH SỬ
        supabase.table("chat_history").insert({
            "session_id": request.session_id,
            "user_message": request.user_message,
            "bot_response": bot_reply,
            "recommended_drugs": thuoc_tuong_ung
        }).execute()

        return {"bot_response": bot_reply}

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"bot_response": " Lỗi hệ thống Backend. Hãy xem Terminal."}
