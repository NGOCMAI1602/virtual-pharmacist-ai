// Tạo session_id ngẫu nhiên cho mỗi lần mở web
const sessionId = "session_" + Math.random().toString(36).substring(2, 9);
const chatBox = document.getElementById('chat-box');
const userInput = document.getElementById('user-input');
const sendBtn = document.getElementById('send-btn');
const aiStatus = document.getElementById('ai-status');

// Tương tác Mini AI khi focus vào ô chat
userInput.addEventListener('focus', () => {
    aiStatus.textContent = "Hãy mô tả chi tiết để tôi phân tích nhé!";
});

userInput.addEventListener('blur', () => {
    if(userInput.value.trim() === "") {
        aiStatus.textContent = "Sẵn sàng hỗ trợ bạn";
    }
});

// Hàm thêm tin nhắn vào màn hình
// Hàm thêm tin nhắn vào màn hình (Đã nâng cấp hiển thị)
function appendMessage(text, sender) {
    const msgDiv = document.createElement('div');
    msgDiv.classList.add('message', sender === 'user' ? 'user-message' : 'bot-message');
    
    // Ép kiểu render Markdown cơ bản cho HTML hiểu
    let formattedText = text
        .replace(/\*\*(.*?)\*\*/g, '<b>$1</b>') // In đậm
        .replace(/\*(.*?)\*/g, '<i>$1</i>')     // In nghiêng
        .replace(/\n/g, '<br>');                // Xuống dòng (Quan trọng nhất)
        
    msgDiv.innerHTML = formattedText;
    chatBox.appendChild(msgDiv);
    chatBox.scrollTop = chatBox.scrollHeight;
}

// Xử lý gửi tin nhắn
async function sendMessage() {
    const text = userInput.value.trim();
    if (!text) return;

    appendMessage(text, 'user');
    userInput.value = '';
    
    // Đổi trạng thái AI
    aiStatus.textContent = "Đang quét cơ sở dữ liệu WebMD...";
    const loadingId = "loading_" + Date.now();
    appendMessage("...", "bot"); 
    chatBox.lastChild.id = loadingId; // Tin nhắn chờ

    try {
        const response = await fetch('http://127.0.0.1:8000/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: sessionId, user_message: text })
        });

        const data = await response.json();
        
        // Xóa tin nhắn chờ và in kết quả
        document.getElementById(loadingId).remove();
        appendMessage(data.bot_response, 'bot');
        aiStatus.textContent = "Sẵn sàng hỗ trợ bạn";

    } catch (error) {
        document.getElementById(loadingId).remove();
        appendMessage("Xin lỗi, hệ thống máy chủ đang gặp sự cố kết nối.", 'bot');
        aiStatus.textContent = "Mất kết nối!";
    }
}

sendBtn.addEventListener('click', sendMessage);
userInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') sendMessage();
});