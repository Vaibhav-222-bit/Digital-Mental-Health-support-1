# app.py
import streamlit as st
import sqlite3
import pandas as pd
import altair as alt
import os
import datetime
import json
import random
import hashlib
from pathlib import Path

# Optional OpenAI usage (only if OPENAI_API_KEY set)
USE_OPENAI = bool(os.getenv("OPENAI_API_KEY"))
if USE_OPENAI:
    import openai

# ---------- CONFIG ----------
DB_PATH = "mental_platform.db"
FERNET_KEY = os.getenv("FERNET_KEY")  # optional — base64 key from Fernet.generate_key()
MOD_PASSWORD = os.getenv("MOD_PASSWORD", "modpass123")  # Change in deployment
EMERGENCY_HELPLINE =  """Please reach out for immediate help. You are not alone.\n\n
                📞 National Suicide Prevention Lifeline (India): 9152987821\n\n
                📞 KIRAN Mental Health Helpline: 1800-599-0019\n\n
                If you are in immediate danger, please call your local emergency services."""


# Screening thresholds (PHQ-9)
PHQ9_THRESHOLDS = {
    "none_mild": range(0, 10),
    "moderate": range(10, 15),
    "moderately_severe": range(15, 20),
    "severe": range(20, 100)
}
# GAD-7
GAD7_THRESHOLDS = {
    "none_mild": range(0, 10),
    "moderate": range(10, 15),
    "severe": range(15, 22)
}

# ---------- DATABASE SETUP ----------
def get_db_connection():
    """Establishes connection to the SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initializes the database schema."""
    conn = get_db_connection()
    c = conn.cursor()
    # Users table
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL
        )
    ''')
    # Journal entries
    c.execute('''
        CREATE TABLE IF NOT EXISTS journal_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            entry_text TEXT,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    # Mood tracker
    c.execute('''
        CREATE TABLE IF NOT EXISTS mood_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            mood_score INTEGER, -- e.g., 1-5
            mood_notes TEXT,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    # Screening results
    c.execute('''
        CREATE TABLE IF NOT EXISTS screening_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            test_type TEXT, -- 'PHQ-9' or 'GAD-7'
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            score INTEGER,
            category TEXT,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    # Connect Page Posts
    c.execute('''
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY,
                user_id INTEGER,
                username TEXT,
                content TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        ''')
    conn.commit()
    conn.close()

# Ensure DB is initialized on first run
if not os.path.exists(DB_PATH):
    init_db()

# ---------- AUTHENTICATION HELPERS ----------
def hash_password(password):
    """Hashes a password using SHA-256."""
    return hashlib.sha256(password.encode()).hexdigest()

def signup(username, password):
    """Signs up a new user."""
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, hash_password(password)))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False # Username already exists
    finally:
        conn.close()

def login(username, password):
    """Logs in an existing user."""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE username = ? AND password = ?", (username, hash_password(password)))
    user = c.fetchone()
    conn.close()
    return user

# ------------------------
# FEATURE PAGES
# ------------------------

def journal_page():
    st.header("My Private Journal ✍️")
    st.write("Reflect on your thoughts and feelings. This is a safe space for you.")

    entry = st.text_area("New entry:", height=200, key="journal_entry")
    if st.button("Save Entry"):
        if entry:
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("INSERT INTO journal_entries (user_id, entry_text) VALUES (?, ?)",
                      (st.session_state.user_id, entry))
            conn.commit()
            conn.close()
            st.success("Journal entry saved!")
            st.experimental_rerun()
        else:
            st.warning("Please write something before saving.")

    st.subheader("Past Entries")
    conn = get_db_connection()
    entries = pd.read_sql_query(f"SELECT timestamp, entry_text FROM journal_entries WHERE user_id = {st.session_state.user_id} ORDER BY timestamp DESC", conn)
    conn.close()

    if entries.empty:
        st.info("You haven't written any journal entries yet.")
    else:
        for index, row in entries.iterrows():
            with st.expander(f"Entry from {row['timestamp']}"):
                st.write(row['entry_text'])

def mood_tracker_page():
    st.header("Mood Tracker 😊😐😟")
    st.write("How are you feeling today?")

    mood_score = st.slider("Rate your mood (1=Very Bad, 5=Very Good):", 1, 5, 3)
    mood_notes = st.text_input("Any specific thoughts? (optional)")

    if st.button("Log Mood"):
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("INSERT INTO mood_entries (user_id, mood_score, mood_notes) VALUES (?, ?, ?)",
                  (st.session_state.user_id, mood_score, mood_notes))
        conn.commit()
        conn.close()
        st.success("Mood logged successfully!")

    st.subheader("Your Mood History")
    conn = get_db_connection()
    mood_data = pd.read_sql_query(f"SELECT timestamp, mood_score FROM mood_entries WHERE user_id = {st.session_state.user_id} ORDER BY timestamp ASC", conn, parse_dates=['timestamp'])
    conn.close()

    if mood_data.empty:
        st.info("No mood data logged yet. Track your mood to see trends here.")
    else:
        chart = alt.Chart(mood_data).mark_line(point=True).encode(
            x=alt.X('timestamp:T', title='Date'),
            y=alt.Y('mood_score:Q', title='Mood Score', scale=alt.Scale(domain=[1, 5])),
            tooltip=['timestamp:T', 'mood_score:Q']
        ).properties(
            title="Your Mood Over Time"
        ).interactive()
        st.altair_chart(chart, use_container_width=True)

def screening_page():
    st.header("Self-Screening Tools 📝")
    st.info("These are not diagnostic tools. They are meant to help you understand your feelings. Please consult a professional for a diagnosis.")

    test = st.selectbox("Choose a screening test:", ["PHQ-9 (Depression)", "GAD-7 (Anxiety)"])

    if test == "PHQ-9 (Depression)":
        questions = [
            "Little interest or pleasure in doing things",
            "Feeling down, depressed, or hopeless",
            "Trouble falling or staying asleep, or sleeping too much",
            "Feeling tired or having little energy",
            "Poor appetite or overeating",
            "Feeling bad about yourself — or that you are a failure or have let yourself or your family down",
            "Trouble concentrating on things, such as reading the newspaper or watching television",
            "Moving or speaking so slowly that other people could have noticed? Or the opposite — being so fidgety or restless that you have been moving around a lot more than usual",
            "Thoughts that you would be better off dead or of hurting yourself in some way"
        ]
        options = ["Not at all", "Several days", "More than half the days", "Nearly every day"]
        scores = {option: i for i, option in enumerate(options)}

        results = []
        for i, q in enumerate(questions):
            answer = st.radio(f"{i+1}. {q}", options, key=f"phq9_{i}")
            results.append(scores[answer])

        if st.button("Calculate My PHQ-9 Score"):
            total_score = sum(results)
            category = "Unknown"
            if total_score in PHQ9_THRESHOLDS["none_mild"]: category = "None to Mild Depression"
            elif total_score in PHQ9_THRESHOLDS["moderate"]: category = "Moderate Depression"
            elif total_score in PHQ9_THRESHOLDS["moderately_severe"]: category = "Moderately Severe Depression"
            elif total_score in PHQ9_THRESHOLDS["severe"]: category = "Severe Depression"

            st.subheader(f"Your score is: {total_score}")
            st.write(f"This suggests: **{category}**")

            # Save result
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("INSERT INTO screening_results (user_id, test_type, score, category) VALUES (?, ?, ?, ?)",
                      (st.session_state.user_id, "PHQ-9", total_score, category))
            conn.commit()
            conn.close()

            if total_score >= 10:
                st.warning("Your score indicates you may benefit from talking to a mental health professional.")
                st.info(EMERGENCY_HELPLINE)

    elif test == "GAD-7 (Anxiety)":
        questions = [
            "Feeling nervous, anxious, or on edge",
            "Not being able to stop or control worrying",
            "Worrying too much about different things",
            "Trouble relaxing",
            "Being so restless that it is hard to sit still",
            "Becoming easily annoyed or irritable",
            "Feeling afraid as if something awful might happen"
        ]
        options = ["Not at all", "Several days", "More than half the days", "Nearly every day"]
        scores = {option: i for i, option in enumerate(options)}

        results = []
        for i, q in enumerate(questions):
            answer = st.radio(f"{i+1}. {q}", options, key=f"gad7_{i}")
            results.append(scores[answer])

        if st.button("Calculate My GAD-7 Score"):
            total_score = sum(results)
            category = "Unknown"
            if total_score in GAD7_THRESHOLDS["none_mild"]: category = "None to Mild Anxiety"
            elif total_score in GAD7_THRESHOLDS["moderate"]: category = "Moderate Anxiety"
            elif total_score in GAD7_THRESHOLDS["severe"]: category = "Severe Anxiety"

            st.subheader(f"Your score is: {total_score}")
            st.write(f"This suggests: **{category}**")

            # Save result
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("INSERT INTO screening_results (user_id, test_type, score, category) VALUES (?, ?, ?, ?)",
                      (st.session_state.user_id, "GAD-7", total_score, category))
            conn.commit()
            conn.close()

            if total_score >= 10:
                st.warning("Your score indicates you may benefit from talking to a mental health professional.")
                st.info(EMERGENCY_HELPLINE)

def resources_page():
    st.header("Helpful Resources 📚")
    st.write("You are not alone. Here are some resources that can help.")

    st.subheader("Emergency Helplines")
    st.info(EMERGENCY_HELPLINE)

    st.subheader("Articles and Information")
    resources = {
        "Understanding Anxiety": "https://www.nimh.nih.gov/health/topics/anxiety-disorders",
        "Coping with Depression": "https://www.helpguide.org/articles/depression/coping-with-depression.htm",
        "Mindfulness for Beginners": "https://www.mindful.org/meditation/mindfulness-getting-started/",
        "iCALL Psychosocial Helpline": "https://icallhelpline.org/"
    }
    for title, url in resources.items():
        st.markdown(f"- [{title}]({url})")

def chatbot_page():
    st.header("AI Companion Chatbot 🤖")
    st.write("Talk about anything on your mind. I'm here to listen without judgment.")
    st.warning("I am an AI and not a substitute for professional help. Please use the resources page if you are in crisis.", icon="⚠️")

    if not USE_OPENAI:
        st.error("The AI chatbot is currently unavailable. The app owner needs to set an `OPENAI_API_KEY` environment variable.")
        return

    openai.api_key = os.getenv("OPENAI_API_KEY")

    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "system", "content": "You are a kind, empathetic, and supportive mental health companion. Your goal is to listen, validate feelings, and provide a safe space. Do not give medical advice. If the user expresses thoughts of self-harm or is in a crisis, gently guide them to the emergency resources provided in the app."}]

    for message in st.session_state.messages:
        if message["role"] != "system":
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

    if prompt := st.chat_input("What is on your mind?"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            message_placeholder = st.empty()
            full_response = ""
            try:
                for response in openai.ChatCompletion.create(
                    model="gpt-3.5-turbo",
                    messages=[{"role": m["role"], "content": m["content"]} for m in st.session_state.messages],
                    stream=True,
                ):
                    full_response += response.choices[0].delta.get("content", "")
                    message_placeholder.markdown(full_response + "▌")
                message_placeholder.markdown(full_response)
            except Exception as e:
                full_response = f"Sorry, I encountered an error. Please try again. Error: {e}"
                message_placeholder.markdown(full_response)

        st.session_state.messages.append({"role": "assistant", "content": full_response})

def instachat_page():
    """
    This function renders the real-time chat application as an embedded HTML component.
    """
    st.header("InstaChat - Connect with Others 💬")
    st.info("Chat in real-time with other users on the platform. You can discover new people, send friend requests, and have private conversations.")
    
    # IMPORTANT: The user must create a Firebase project and paste their config here.
    firebase_config_string = """
    {
        "apiKey": "YOUR_API_KEY",
        "authDomain": "YOUR_AUTH_DOMAIN",
        "projectId": "YOUR_PROJECT_ID",
        "storageBucket": "YOUR_STORAGE_BUCKET",
        "messagingSenderId": "YOUR_MESSAGING_SENDER_ID",
        "appId": "YOUR_APP_ID"
    }
    """
    
    # Check if the user has replaced the placeholder config
    try:
        is_config_default = '"YOUR_API_KEY"' in firebase_config_string
        if is_config_default:
            st.error("Action Required: The chat feature is not configured. Please create a Firebase project, enable Firestore, and paste your web app's Firebase configuration into the `firebase_config_string` in the `instachat_page` function in the `app.py` file.")
            st.code(firebase_config_string, language="json")
            return
    except:
        st.error("There is an error in your Firebase configuration string. Please ensure it is valid JSON.")
        return


    # We use the Streamlit username to create a unique, stable ID for the chat user.
    # This avoids needing a separate login for the chat.
    current_username = st.session_state.get('username', 'anonymous')
    # Simple hash to create a UID from the username for Firebase
    uid_hash = hashlib.sha256(current_username.encode()).hexdigest()

    # The entire chat app is a single HTML file embedded here.
    chat_html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>InstaChat</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }}
            ::-webkit-scrollbar {{ width: 5px; }}
            ::-webkit-scrollbar-track {{ background: #1f2937; }}
            ::-webkit-scrollbar-thumb {{ background: #4b5563; border-radius: 10px; }}
            ::-webkit-scrollbar-thumb:hover {{ background: #6b7280; }}
        </style>
    </head>
    <body class="bg-gray-900 text-white">
        <div id="app-container" class="h-screen w-full flex font-sans antialiased">
            <!-- This container will be populated by JavaScript -->
        </div>

        <script type="module">
            // Import Firebase modules
            import {{ initializeApp }} from "https://www.gstatic.com/firebasejs/9.15.0/firebase-app.js";
            import {{ getAuth, signInAnonymously, onAuthStateChanged }} from "https://www.gstatic.com/firebasejs/9.15.0/firebase-auth.js";
            import {{ 
                getFirestore, doc, setDoc, getDoc, collection, onSnapshot, addDoc, 
                query, orderBy, serverTimestamp, where, updateDoc, arrayUnion, deleteDoc, getDocs 
            }} from "https://www.gstatic.com/firebasejs/9.15.0/firebase-firestore.js";

            // --- App State ---
            let user = null;
            let userData = null;
            let allUsers = [];
            let friends = [];
            let friendRequests = [];
            let sentRequests = [];
            let selectedUser = null;
            let messages = [];
            let activeTab = 'discover';
            let db, auth;

            // --- Injected from Streamlit ---
            const firebaseConfig = JSON.parse(`{firebase_config_string}`);
            const currentUsername = "{current_username}";
            const currentUid = "{uid_hash}";
            const appId = firebaseConfig.projectId || 'default-app-id';

            // --- Main App Function ---
            function main() {{
                try {{
                    const app = initializeApp(firebaseConfig);
                    db = getFirestore(app);
                    auth = getAuth(app);
                    
                    onAuthStateChanged(auth, async (currentUser) => {{
                        if (currentUser) {{
                            // The user is signed in.
                            // We use the UID hashed from the Streamlit username.
                            user = {{ uid: currentUid }}; 
                            const userDocRef = doc(db, `artifacts/${{appId}}/users`, user.uid);
                            
                            // Set or update user's online status and display name
                            await setDoc(userDocRef, {{ 
                                uid: user.uid,
                                displayName: currentUsername,
                                isOnline: true,
                            }}, {{ merge: true }});
                            
                            // Start listening to data
                            setupListeners();
                        }} else {{
                            // User is signed out. Sign them in anonymously.
                            signInAnonymously(auth).catch(error => console.error("Anonymous sign-in failed:", error));
                        }}
                    }});

                }} catch (error) {{
                    console.error("Error initializing Firebase:", error);
                    document.getElementById('app-container').innerHTML = `<div class="p-4 text-red-400">Error: Could not initialize Firebase. Check console for details.</div>`;
                }}
            }}

            // --- Firestore Listeners ---
            function setupListeners() {{
                // Listen to current user's data (for friends list)
                const userDocRef = doc(db, `artifacts/${{appId}}/users`, user.uid);
                onSnapshot(userDocRef, (doc) => {{
                    if (doc.exists()) {{
                        userData = doc.data();
                        renderApp();
                        setupFriendListener();
                    }}
                }});

                // Listen for all online users
                const usersCollectionRef = collection(db, `artifacts/${{appId}}/users`);
                const q = query(usersCollectionRef, where("isOnline", "==", true));
                onSnapshot(q, (snapshot) => {{
                    allUsers = snapshot.docs
                        .map(doc => doc.data())
                        .filter(u => u.uid !== user.uid); 
                    renderApp();
                }});

                // Listen for friend requests
                const requestsRef = collection(db, `artifacts/${{appId}}/friendRequests`);
                const incomingQuery = query(requestsRef, where("receiverId", "==", user.uid), where("status", "==", "pending"));
                onSnapshot(incomingQuery, async (snapshot) => {{
                    const requests = snapshot.docs.map(d => ({{ id: d.id, ...d.data() }}));
                    const senderIds = requests.map(r => r.senderId).filter(id => id);
                    if(senderIds.length === 0) {{
                        friendRequests = [];
                        renderApp();
                        return;
                    }};
                    const sendersQuery = query(collection(db, `artifacts/${{appId}}/users`), where('uid', 'in', senderIds));
                    const senderDocs = await getDocs(sendersQuery);
                    const sendersMap = senderDocs.docs.reduce((acc, doc) => {{
                        acc[doc.id] = doc.data();
                        return acc;
                    }}, {{}});
                    friendRequests = requests.map(r => ({{...r, sender: sendersMap[r.senderId]}}));
                    renderApp();
                }});

                const sentQuery = query(requestsRef, where("senderId", "==", user.uid), where("status", "==", "pending"));
                onSnapshot(sentQuery, (snapshot) => {{
                    sentRequests = snapshot.docs.map(d => ({{ id: d.id, ...d.data() }}));
                    renderApp();
                }});
            }}

            function setupFriendListener() {{
                if (!userData || !userData.friends || userData.friends.length === 0) {{
                    friends = [];
                    renderApp();
                    return;
                }}
                const friendsQuery = query(collection(db, `artifacts/${{appId}}/users`), where('uid', 'in', userData.friends));
                onSnapshot(friendsQuery, (snapshot) => {{
                    friends = snapshot.docs.map(doc => doc.data());
                    renderApp();
                }});
            }}

            let messagesUnsubscribe = null;
            function setupMessagesListener(targetUser) {{
                if (messagesUnsubscribe) messagesUnsubscribe(); // Detach old listener
                
                const chatId = [user.uid, targetUser.uid].sort().join('_');
                const messagesCollectionRef = collection(db, 'chats', chatId, 'messages');
                const q = query(messagesCollectionRef, orderBy('timestamp', 'asc'));

                messagesUnsubscribe = onSnapshot(q, (snapshot) => {{
                    messages = snapshot.docs.map(doc => ({{ id: doc.id, ...doc.data() }}));
                    renderApp();
                    scrollToBottom();
                }});
            }}

            // --- UI Rendering ---
            function renderApp() {{
                const container = document.getElementById('app-container');
                if (!user || !userData) {{
                    container.innerHTML = `<div class="w-full flex items-center justify-center"><div class="animate-spin rounded-full h-16 w-16 border-t-2 border-b-2 border-blue-500"></div></div>`;
                    return;
                }}
                container.innerHTML = `
                    ${{renderSidebar()}}
                    ${{renderChatArea()}}
                `;
                addEventListeners();
            }}

            function renderSidebar() {{
                 return `
                    <div class="w-full md:w-1/3 lg:w-1/4 border-r border-gray-700 flex flex-col">
                        <div class="p-4 border-b border-gray-700">
                            <h2 class="text-xl font-bold truncate">${{userData.displayName}}'s Chat</h2>
                        </div>
                        <div class="p-2 border-b border-gray-700">
                            <div class="flex bg-gray-800 rounded-lg">
                                ${ {TabButton({ tabName: "discover", label: "Discover" })} }
                                ${ {TabButton({ tabName: "friends", label: "Friends" })} }
                                <div class="relative flex-1">
                                    ${ {TabButton({ tabName: "requests", label: "Requests" })} }
                                </div>
                            </div>
                        </div>
                        <div class="flex-1 overflow-y-auto" id="user-list-container">
                            ${{renderUserList()}}
                        </div>
                    </div>
                `;
            }}

            function TabButton({{ tabName, label }}) {{
                const isActive = activeTab === tabName;
                const hasBadge = tabName === 'requests' && friendRequests.length > 0;
                return `
                    <button data-tab="${{tabName}}" class="tab-button flex-1 p-2 text-sm rounded-md transition-colors duration-200 ${{isActive ? 'bg-gray-700 text-white' : 'text-gray-400 hover:bg-gray-800'}}">
                        ${{label}}
                        ${{hasBadge ? `<span class="ml-2 h-5 w-5 bg-red-500 text-white text-xs rounded-full flex items-center justify-center">${{friendRequests.length}}</span>` : ''}}
                    </button>
                `;
            }}

            function renderUserList() {{
                let usersToDisplay = [];
                let emptyMessage = "";

                switch(activeTab) {{
                    case 'friends':
                        usersToDisplay = friends;
                        emptyMessage = "You haven't added any friends yet.";
                        break;
                    case 'requests':
                        usersToDisplay = friendRequests.map(req => ({{...(req.sender || {{uid: 'unknown', displayName: 'Loading...'}}), requestId: req.id}}));
                        emptyMessage = "No new friend requests.";
                        break;
                    case 'discover':
                    default:
                        usersToDisplay = allUsers;
                        emptyMessage = "No other users are online.";
                        break;
                }}

                if (usersToDisplay.length === 0) {{
                    return `<p class="text-gray-400 text-center p-4">${{emptyMessage}}</p>`;
                }}
                
                return usersToDisplay.map(u => `
                    <div data-uid="${{u.uid}}" data-displayname="${{u.displayName}}" class="user-list-item flex items-center p-3 cursor-pointer hover:bg-gray-800 transition-colors duration-200 ${{selectedUser?.uid === u.uid ? 'bg-gray-700' : ''}}">
                        ${{Avatar(u.uid)}}
                        <div class="ml-4 flex-1 min-w-0">
                            <p class="font-semibold truncate">${{u.displayName || 'User'}}</p>
                        </div>
                        ${{renderUserAction(u)}}
                    </div>
                `).join('');
            }}

            function renderUserAction(u) {{
                if (activeTab === 'discover') {{
                    const status = getFriendshipStatus(u);
                     switch(status) {{
                        case 'friends': return `<span class="text-xs text-green-400">Friends</span>`;
                        case 'sent': return `<span class="text-xs text-gray-400">Sent</span>`;
                        case 'incoming': return `<button data-action="accept" data-requestid="${{friendRequests.find(r=>r.senderId === u.uid).id}}" data-senderid="${{u.uid}}" class="text-xs bg-blue-600 px-2 py-1 rounded">Accept</button>`;
                        default: return `<button data-action="send" data-receiverid="${{u.uid}}" class="p-2 rounded-full hover:bg-gray-700 text-gray-300">➕</button>`;
                    }}
                }}
                if (activeTab === 'requests') {{
                    return `
                        <div class="ml-auto flex items-center space-x-2">
                            <button data-action="accept" data-requestid="${{u.requestId}}" data-senderid="${{u.uid}}" class="p-2 rounded-full bg-green-600 hover:bg-green-700">✔️</button>
                            <button data-action="decline" data-requestid="${{u.requestId}}" class="p-2 rounded-full bg-red-600 hover:bg-red-700">❌</button>
                        </div>
                    `;
                }}
                return '';
            }}

            function renderChatArea() {{
                if (!selectedUser) {{
                    return `
                        <div class="hidden md:flex w-2/3 lg:w-3/4 flex-col items-center justify-center h-full text-center text-gray-400 p-4">
                            <svg xmlns="http://www.w3.org/2000/svg" class="w-24 h-24 mb-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" /></svg>
                            <h2 class="text-2xl font-bold text-white">Welcome to InstaChat</h2>
                            <p>Select a user to start a conversation.</p>
                        </div>
                    `;
                }}
                return `
                    <div class="hidden md:flex w-2/3 lg:w-3/4 flex-col">
                        <div class="flex items-center p-3 border-b border-gray-700 bg-gray-800/50">
                            ${{Avatar(selectedUser.uid)}}
                            <p class="ml-4 font-bold">${{selectedUser.displayName}}</p>
                        </div>
                        <div class="flex-1 p-4 overflow-y-auto" id="messages-container">
                            ${{messages.map(msg => `
                                <div class="flex my-2 ${{msg.senderId === user.uid ? 'justify-end' : 'justify-start'}}">
                                    <div class="max-w-xs lg:max-w-md px-4 py-2 rounded-2xl ${{msg.senderId === user.uid ? 'bg-blue-600 rounded-br-none' : 'bg-gray-700 rounded-bl-none'}}">
                                        <p class="text-sm break-words">${{escapeHTML(msg.text)}}</p>
                                    </div>
                                </div>
                            `).join('')}}
                            <div id="messages-end"></div>
                        </div>
                        <div class="p-4 bg-gray-800/50 border-t border-gray-700">
                            <form id="message-form" class="flex items-center">
                                <input id="message-input" type="text" placeholder="Type a message..." class="flex-1 bg-gray-700 rounded-full px-4 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 text-white">
                                <button type="submit" class="ml-3 px-4 py-2 bg-blue-600 rounded-full font-semibold hover:bg-blue-700 transition-colors duration-200 disabled:opacity-50">Send</button>
                            </form>
                        </div>
                    </div>
                `;
            }}
            
            // --- Event Handling ---
            function addEventListeners() {{
                // Tab switching
                document.querySelectorAll('.tab-button').forEach(btn => {{
                    btn.onclick = (e) => {{
                        activeTab = e.currentTarget.dataset.tab;
                        renderApp();
                    }};
                }});

                // Selecting a user to chat with
                document.querySelectorAll('.user-list-item').forEach(item => {{
                    if (activeTab !== 'requests') {{
                        item.onclick = (e) => {{
                            selectedUser = {{ uid: item.dataset.uid, displayName: item.dataset.displayname }};
                            setupMessagesListener(selectedUser);
                            renderApp();
                        }};
                    }}
                }});

                // Friend request buttons
                document.querySelectorAll('[data-action]').forEach(btn => {{
                    btn.onclick = (e) => {{
                        e.stopPropagation();
                        const {{ action, receiverid, requestid, senderid }} = e.currentTarget.dataset;
                        if (action === 'send') handleSendRequest(receiverid);
                        if (action === 'accept') handleAcceptRequest({{ id: requestid, senderId: senderid }});
                        if (action === 'decline') handleDeclineRequest(requestid);
                    }};
                }});

                // Message form
                const form = document.getElementById('message-form');
                if (form) {{
                    form.onsubmit = handleSendMessage;
                }}
            }}
            
            async function handleSendRequest(receiverId) {{
                const requestsRef = collection(db, `artifacts/${{appId}}/friendRequests`);
                await addDoc(requestsRef, {{
                    senderId: user.uid, receiverId: receiverId, status: "pending", timestamp: serverTimestamp()
                }});
            }}

            async function handleAcceptRequest(request) {{
                const requestDocRef = doc(db, `artifacts/${{appId}}/friendRequests`, request.id);
                const currentUserDocRef = doc(db, `artifacts/${{appId}}/users`, user.uid);
                const senderDocRef = doc(db, `artifacts/${{appId}}/users`, request.senderId);

                await updateDoc(currentUserDocRef, {{ friends: arrayUnion(request.senderId) }});
                await updateDoc(senderDocRef, {{ friends: arrayUnion(user.uid) }});
                await deleteDoc(requestDocRef);
            }}

            async function handleDeclineRequest(requestId) {{
                await deleteDoc(doc(db, `artifacts/${{appId}}/friendRequests`, requestId));
            }}

            async function handleSendMessage(e) {{
                e.preventDefault();
                const input = document.getElementById('message-input');
                const text = input.value.trim();
                if (text === '' || !selectedUser) return;
                
                const chatId = [user.uid, selectedUser.uid].sort().join('_');
                const messagesCollectionRef = collection(db, 'chats', chatId, 'messages');
                
                input.value = '';
                await addDoc(messagesCollectionRef, {{
                    text: text, senderId: user.uid, timestamp: serverTimestamp()
                }});
            }}

            // --- Helpers ---
            function getFriendshipStatus(targetUser) {{
                if (userData?.friends?.includes(targetUser.uid)) return "friends";
                if (sentRequests.some(req => req.receiverId === targetUser.uid)) return "sent";
                if (friendRequests.some(req => req.senderId === targetUser.uid)) return "incoming";
                return null;
            }}

            function stringToColor(str) {{
                let hash = 0;
                if (!str || str.length === 0) return '#cccccc';
                for (let i = 0; i < str.length; i++) {{
                    hash = str.charCodeAt(i) + ((hash << 5) - hash);
                }}
                let color = '#';
                for (let i = 0; i < 3; i++) {{
                    const value = (hash >> (i * 8)) & 0xFF;
                    color += ('00' + value.toString(16)).substr(-2);
                }}
                return color;
            }}

            function Avatar(uid) {{
                const color = stringToColor(uid);
                const initial = uid ? uid.charAt(0).toUpperCase() : '?';
                return `<div class="relative flex items-center justify-center w-10 h-10 rounded-full text-white font-bold flex-shrink-0" style="background-color: ${{color}};">
                    ${{initial}}
                    <span class="absolute bottom-0 right-0 block h-3 w-3 bg-green-400 border-2 border-gray-900 rounded-full"></span>
                </div>`;
            }}

            function scrollToBottom() {{
                const el = document.getElementById('messages-end');
                if (el) el.scrollIntoView({{ behavior: 'smooth' }});
            }}

            function escapeHTML(str) {{
                return str.replace(/[&<>"']/g, function(match) {{
                    return {{
                        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
                    }}[match];
                }});
            }}

            // --- Start the App ---
            main();

        </script>
    </body>
    </html>
    """
    
    st.components.v1.html(chat_html, height=700, scrolling=True)


# ------------------------
# MAIN APP LOGIC
# ------------------------
def main():
    st.set_page_config(page_title="Mental Well-being Platform", layout="wide")

    # Initialize session state variables
    if 'logged_in' not in st.session_state:
        st.session_state.logged_in = False
    if 'is_moderator' not in st.session_state:
        st.session_state.is_moderator = False
    if 'current_page' not in st.session_state:
        st.session_state.current_page = "Home"

    # --- LOGIN/SIGNUP/LOGOUT Sidebar ---
    with st.sidebar:
        st.title("Navigation")
        if st.session_state.logged_in:
            st.success(f"Logged in as **{st.session_state.username}**")
            if st.button("Logout"):
                st.session_state.logged_in = False
                st.session_state.is_moderator = False
                st.session_state.current_page = "Home"
                del st.session_state.username
                del st.session_state.user_id
                st.experimental_rerun()
        else:
            login_form = st.form("login_form")
            login_form.subheader("Login")
            username = login_form.text_input("Username", key="login_user")
            password = login_form.text_input("Password", type="password", key="login_pass")
            if login_form.form_submit_button("Login"):
                if username == "moderator" and password == MOD_PASSWORD:
                    st.session_state.logged_in = True
                    st.session_state.is_moderator = True
                    st.session_state.username = "moderator"
                    st.session_state.user_id = 0 # special ID for mod
                    st.experimental_rerun()
                else:
                    user = login(username, password)
                    if user:
                        st.session_state.logged_in = True
                        st.session_state.username = user['username']
                        st.session_state.user_id = user['id']
                        st.experimental_rerun()
                    else:
                        st.error("Invalid username or password")

            signup_form = st.form("signup_form")
            signup_form.subheader("Sign Up")
            new_username = signup_form.text_input("New Username", key="signup_user")
            new_password = signup_form.text_input("New Password", type="password", key="signup_pass")
            if signup_form.form_submit_button("Sign Up"):
                if signup(new_username, new_password):
                    st.success("Account created! Please log in.")
                else:
                    st.error("Username already exists.")

    # --- PAGE ROUTING ---
    if not st.session_state.logged_in:
        st.title("Welcome to the Mental Well-being Platform")
        st.write("Please log in or sign up using the sidebar to access the platform's features.")
        return

    # Dictionary mapping page names to functions
    pages = {
        "Home": None, # Special case for home
        "My Journal": journal_page,
        "Mood Tracker": mood_tracker_page,
        "Self-Screening": screening_page,
        "InstaChat": instachat_page,
        "AI Companion": chatbot_page,
        "Resources": resources_page,
    }

    # --- HOME PAGE ---
    if st.session_state.current_page == "Home":
        st.title(f"Welcome back, {st.session_state.username}!")
        st.write("How can we support you today? Choose a feature to get started.")

        card_styles = {
            "My Journal": "#1E40AF",
            "Mood Tracker": "#065F46",
            "Self-Screening": "#7C2D12",
            "InstaChat": "#86198F",
            "AI Companion": "#4A044E",
            "Resources": "#854D0E"
        }

        # Create cards in columns
        features = list(pages.keys())[1:]  # exclude Home
        
        # Create a grid layout
        col1, col2, col3 = st.columns(3)
        cols = [col1, col2, col3]

        for i, feature in enumerate(features):
            with cols[i % 3]:
                # Using st.container to group the button and visual representation
                with st.container():
                    # Make the entire visual card clickable by using a button with custom CSS
                    if st.button(feature, key=feature, use_container_width=True):
                        st.session_state.current_page = feature
                        st.experimental_rerun()
                    
                    # This markdown creates the visual style of the card.
                    # Note: Streamlit's button gets styled minimally, so we place a visual div "below" it conceptually.
                    # A small hack is needed to overlay the button's click area over the visual.
                    # We will use simple cards for better compatibility.
                    
        # A more robust way to create clickable cards in Streamlit:
        st.markdown("""<hr>""", unsafe_allow_html=True)
        cols = st.columns(3)
        for i, feature in enumerate(features):
            with cols[i % 3]:
                st.markdown(f"""
                <a href="#" id="{feature.replace(" ", "")}" class="card-link">
                    <div style="background-color:{card_styles[feature]}; padding:20px; border-radius:10px; color:white; text-align:center; margin-bottom: 20px;">
                        <h3>{feature}</h3>
                    </div>
                </a>
                """, unsafe_allow_html=True)

                if st.button(f"Go to {feature}", key=f"btn_{feature}", use_container_width=True):
                    st.session_state.current_page = feature
                    st.experimental_rerun()

    # --- RUN SELECTED PAGE ---
    else:
        # Back to Home button at the top
        if st.button("⬅ Back to Home"):
            st.session_state.current_page = "Home"
            st.experimental_rerun() # Rerun to immediately go home
        
        # Render the selected page
        page_function = pages.get(st.session_state.current_page)
        if page_function:
            page_function()


if __name__ == "__main__":
    main()