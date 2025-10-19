import streamlit as st
from langchain_google_genai import ChatGoogleGenerativeAI 
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, HumanMessageChunk
from io import BytesIO
import base64
import random
import json
import mysql.connector

app_id = "chatbot_sehat"
if "user_id" not in st.session_state : 
    st.session_state.user_id = f"anon-{random.randint(1000,9999)}"

#-----------SIMPAN RIWAYAT CHAT------#
def save_chat_history(role, content):
    """
    Menyimpan pesar (dari user atau dari asisten) ke dalam tabel chat_history MySQL. 
    Mengambil kredensial dari st.secrets["mysql]
    """
    try:
        db_config = st.secrets["mysql"]
        
        conn = mysql.connector.connect(
            host=db_config["host"],
            user=db_config["user"],
            password=db_config["password"],
            database=db_config["database"]
        )
        cursor = conn.cursor()
        sql = """
        INSERT INTO chat_history (user_id, app_id, role, content)
        VALUES  (%s, %s, %s, %s)
        """
        data = (st.session_state.user_id, app_id, role, content)
        
        cursor.execute(sql,data)
        
        conn.commit()
        
    
    except KeyError:
        print("Error: Kredensial MySQL tidak ditemukan di secrets.toml. Silahka dipastikan kembali")
    
    except mysql.connector.Error as e:
        print(f"Mysql Error saat menyimpan riwayat: {e}")
        
    finally:
        if "conn" in locals() and conn.is_connected():
            cursor.close()
            conn.close()


    
#------AMBIL API KEY-----#
API_KEY = st.secrets["API_KEY"]

#-----------INISIALISASI SESSION------#
if "conversation" not in st.session_state:
    st.session_state.conversation=[] 

if 'multimodal_history' not in st.session_state:
    st.session_state.multimodal_history = [] 

if 'uploaded_file_state' not in st.session_state:
    st.session_state.uploaded_file_state = None

if  'is_history_loaded' not in st.session_state:
    st.session_state.is_history_loaded = False

#-------Mengambil Riwayat Chat dari Database-----#
def load_chat_history():
    """
    Memuat pesan (dari user atau dari asisten) dari tabel chat
    """
    if st.session_state.is_history_loaded:
        return
        

    conn = None
    try:
        db_config = st.secrets["mysql"]
        
        conn = mysql.connector.connect(
            host = db_config["host"],
            user = db_config["user"],
            password = db_config["password"],
            database = db_config["database"]
        )
        cursor = conn.cursor(dictionary=True)
        
        sql = """
        SELECT role, content FROM chat_history
        WHERE user_id = %s AND app_id = %s
        ORDER BY timestamp
        """
        data = (st.session_state.user_id, app_id)
        
        cursor.execute(sql, data)
        results = cursor.fetchall()
        
        for row in results:
            role = row["role"]
            content = row["content"]
            
            
            st.session_state.conversation.append({"role": role, "content": content})
        
            if role =="user":
                st.session_state.multimodal_history.append(HumanMessage(content=content))
            elif role == "assistant":
                st.session_state.multimodal_history.append(AIMessage(content=content))
    
        st.session_state.is_history_loaded = True
    except Exception as e :
        print(f"Error memuat riwayat dari MySQL; {e}")
        
    finally:
        if conn and conn.is_connected():
                cursor.close()
                conn.close()
                
load_chat_history()
            
#------KONFIGURASI GEMINI-----#
gemini_generation_config={
    "temperature" : 0.4,
    "max_output_tokens" : 1000,
    "top_p" : 0.80,
    "top_k" : 35
}

#------MODEL GEMINI --------#
model = ChatGoogleGenerativeAI(
        model="gemini-2.0-flash",
        google_api_key=API_KEY,
        temperature=gemini_generation_config["temperature"],
        max_output_tokens=gemini_generation_config["max_output_tokens"],
        top_p=gemini_generation_config["top_p"],
        top_k=gemini_generation_config["top_k"]
      )   
st.sidebar.info("Model: Gemini 2.0 Flash | Status : Aktif")
is_rag_active = True

#-------MEMPROSES BERKAS YANG DIUNGGAH-----#
def get_gemini_parts(uploaded_file):
        """Membaca berkas dan mengembalikan sebagai list of content parts."""
        
        #Membaca berkas file
        file_bytes = uploaded_file.read()
        mime_type = uploaded_file.type
        
        #Mengkodekan byte ke base64
        base64_encoded_data = base64.b64encode(file_bytes).decode('utf-8')
        
        return{
                "inlineData": {
                    "data" : base64_encoded_data,
                    "mimeType" : mime_type
                }
            }
        
        
#------UI STREAMLIT--------#
st.set_page_config(page_title="Chatbot Kesehatan", layout="wide")
st.markdown("<h1 style='text-align: center;'>Chatbot Kesehatan</h1>", unsafe_allow_html=True)


#Tempat Input di Tampilan Bar Samping
with st.sidebar :
    st.subheader("Silahkan masukkan berkas")
    uploaded_file = st.file_uploader(
        "Unggah Gambar, PDF, VIdeo atau Suara",
        type=["png","jpg","jpeg", "pdf", "mp4", "mp3"],
        help="Model akan melakukan analisis terhadap konten ini dalam konteks kesehatan", key="file_uploader_key"
    )
    #-----SIMPAN FILE UNGGAHAN----#
    if uploaded_file is not None and st.session_state.uploaded_file_state != uploaded_file: 
        st.session_state.uploaded_file_state = uploaded_file
    
    #-----INFO KONFIGURASI MODEL -------#
    st.subheader("Konfigurasi Model")
    st.info(f"""
- **Temperature:** {gemini_generation_config["temperature"]}
- **Max Tokens:** {gemini_generation_config["max_output_tokens"]}
- **Top-P:** {gemini_generation_config["top_p"]}
- **Top-K:** {gemini_generation_config["top_k"]}
""")
    
    #Hapus Riwayat Chat
    if st.button("Hapus Riwayat Chat", type="secondary"):
       
        st.session_state.conversation = []
        st.session_state.multimodal_history = []
        st.session_state.uploaded_file_state = None
        
        
        
        st.rerun()


user_input = st.chat_input("Berikan pertanyaan mengenai kesehatan")

#------LOGIKA PESAN------#
if user_input:
    
    current_message_parts = [user_input]
    display_content = user_input
    
    file_to_process = st.session_state.uploaded_file_state
    
    if file_to_process :
        try:

            file_part_dict = get_gemini_parts(file_to_process)
            
            current_message_parts.append(file_part_dict)
            
            display_content += f"\n\n**[Berkas Terlampir: {file_to_process.name} ({file_to_process.type})]**"
            
        except Exception as e :
            st.error(f"Gagal memproses berkas : {e}. Silahkan gunakan teks saja")
            file_to_process = None
            
    st.session_state.conversation.append({"role": "user", "content": display_content})
    st.session_state.multimodal_history.append(HumanMessage(content=current_message_parts))
    save_chat_history("user", display_content)    

    
    system_instruction = (
        "***ADVANCE PROMPTING TECHNIQUE***\n"
        "Anda adalah **Spesialis Edukasi Kesehatan Publik & Analis Multimodal** yang sangat etis dan menggunakan penalaran mendalam. "
        "Peran Anda (Meta Prompting) adalah memastikan setiap langkah di bawah diikuti secara ketat. "
        "Fokus utama Anda adalah menganalisis input (teks atau berkas) dan memberikan penjelasan kesehatan.\n"
        
        "**PROTOKOL PENALARAN KOMPREHENSIF:**\n"
        "Untuk setiap permintaan, IKUTI langkah-langkah di bawah secara berurutan dan terstruktur (Prompt Chaining):\n"
        
        "1. **PENGUMPULAN & PRIORITAS PENGETAHUAN (Generate Knowledge / Directional Stimulus):**\n"
        "   a. **Fokus:** Prioritaskan analisis hanya pada aspek kesehatan, medis, atau data pendukung yang relevan (Directional Stimulus).\n"
        "   b. **Generasi:** Kumpulkan dan rangkum semua fakta internal (pengetahuan model) dan eksternal yang diperlukan.\n"
        
        "2. **ANALISIS & RENCANA MULTI-JALUR (ToT / CoT):**\n"
        "   a. **Penalaran:** Lakukan penalaran langkah demi langkah (CoT).\n"
        "   b. **Jalur:** Kembangkan minimal 2-3 jalur solusi yang mungkin (Tree of Thoughts / ToT) untuk memastikan hasil terbaik, terutama untuk pertanyaan yang ambigu.\n"
        
        "3. **VERIFIKASI & PENGGUNAAN ALAT (ReAct / ART / RAG):**\n"
        "   a. **Tindakan:** Gunakan **Google Search Tool** (Action/ART/RAG) untuk memvalidasi setiap klaim yang akan Anda buat dan mencari tren kesehatan terbaru.\n"
        "   b. **Konsistensi:** Bandingkan hasil pencarian dari berbagai sumber dan konsolidasikan menjadi satu fakta yang konsisten (Self-Consistency) sebelum melanjutkan.\n"
        
        "4. **SINTESIS, TINJAUAN & KOREKSI ETIKA (Reflexion):**\n"
        "   a. **Sintesis:** Gabungkan data yang terverifikasi (dari Langkah 3) ke dalam jalur solusi terbaik (dari Langkah 2).\n"
        "   b. **Refleksi:** Tinjau kembali draf jawaban. Pastikan tidak ada saran medis langsung (Reflexion ETIKA) dan pastikan nada tetap empatik.\n"
        
        "**FORMAT RESPON AKHIR:**\n"
        "a. **Jelaskan** konten yang diunggah atau jawab pertanyaan secara komprehensif.\n"
        "b. **Berikan data pendukung** (dari Google Search) dalam format poin-poin terpisah (gunakan Markdown bullets).\n"
        "c. **Tegaskan dengan jelas** bahwa Anda BUKAN DOKTER ATAU PROFESSIONAL MEDIS, dan saran Anda bersifat edukasi.\n"
        "d. **Jawablah** dengan nada yang hangat, empatik, dan mudah dipahami oleh awam."
    )
    langchain_messages = [
        SystemMessage(content=system_instruction)
    ]
    langchain_messages.extend(st.session_state.multimodal_history)
    
    
    #MEMANGGIL MODEL
    try:
        with st.spinner("Mencari informasi terkait kesehatan yang terbaru"):
            response = model.invoke(langchain_messages)
            reply = response.content
            
            st.session_state.conversation.append({"role": "assistant", "content": reply})
            st.session_state.multimodal_history.append(AIMessage(content=reply))
            save_chat_history("assistant", reply)
            
            st.session_state.uploaded_file_state = None
            st.rerun()
           
    except Exception as e:
            error_message = f"Gagal memanggil model: {type(e).__name__}: {str(e)}"
            reply = f"Error: {error_message}"
            st.write(reply)
            st.error(f"Terjadi Kesalahan: {error_message}. Coba Hapus Riwayat Chat.")
            st.session_state.conversation.append({"role": "assistant", "content": reply})
            st.session_state.uploaded_file_state = None
            st.rerun()

#------TAMPILKAN RIWAYAT CHAT------#
for message in st.session_state.conversation:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
            