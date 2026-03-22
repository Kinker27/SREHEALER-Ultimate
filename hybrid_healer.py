import os, requests, re, sqlite3, datetime, subprocess
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# --- CONFIGURATION ---
API_KEY = "AIzaSyD5J8OeHMHdubFkP4meEgN8V17JdM2HaEg"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1/models/gemini-2.5-flash:generateContent?key={API_KEY}"

def init_db():
    conn = sqlite3.connect('sre_audit.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS audit_logs
                 (id INTEGER PRIMARY KEY, timestamp TEXT, lang TEXT, type TEXT, confidence INTEGER)''')
    conn.commit()
    conn.close()

init_db()

def get_project_context():
    context = "\n--- GLOBAL PROJECT CONTEXT ---\n"
    try:
        files = [f for f in os.listdir('.') if f.endswith(('.py', '.js', '.cpp', '.java'))]
        for file in files[:2]:
            with open(file, 'r', errors='ignore') as f:
                context += f"\nFILE: {file}\n{f.read()[:200]}\n"
    except: pass
    return context

def verify_fix(code, lang):
    ext = 'py' if lang == 'python' else 'js' if lang == 'javascript' else 'cpp'
    temp_name = f"verify_temp.{ext}"
    with open(temp_name, 'w', encoding='utf-8') as f: f.write(code)
    try:
        if lang == 'python':
            proc = subprocess.run(['python', temp_name], capture_output=True, text=True, timeout=1.5)
            return proc.returncode == 0, proc.stderr
        return True, ""
    except Exception: return False, "Execution Error"
    finally:
        if os.path.exists(temp_name): os.remove(temp_name)

@app.route('/propose_fix', methods=['POST'])
def propose():
    data = request.json
    code, lang = data.get('code', ''), data.get('language', 'python')
    is_sec = data.get('securityMode', False)
    fast_mode = data.get('fastMode', False)

    ctx = get_project_context()
    mode = "SECURITY_AUDIT" if is_sec else "LOGIC_HEAL"

    prompt = (f"{ctx}\n\nTASK: {mode} on Buffer. Output ONLY: [CODE] | [REASON] | [CONFIDENCE]. No markdown.\n"
              f"BUFFER:\n{code}")

    try:
        r = requests.post(GEMINI_URL, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=10)
        res_data = r.json()

        if 'candidates' not in res_data:
            return jsonify({"proposed": code, "reason": "AI Quota Exceeded", "confidence": 0, "verified": False})

        res_text = res_data['candidates'][0]['content']['parts'][0]['text'].strip()
        res_text = re.sub(r'```[a-z]*|```', '', res_text).strip()

        parts = res_text.split("|")
        proposed = parts[0].strip() if len(parts) > 0 else code
        reason = parts[1].strip() if len(parts) > 1 else "Stability fix applied."
        conf = parts[2].strip() if len(parts) > 2 else "90"

        verified = False
        if not fast_mode and lang == 'python' and len(proposed) > 0:
            success, _ = verify_fix(proposed, lang)
            verified = success

        # Log to Database
        conn = sqlite3.connect('sre_audit.db')
        c = conn.cursor()
        c.execute("INSERT INTO audit_logs (timestamp, lang, type, confidence) VALUES (?,?,?,?)",
                  (datetime.datetime.now().strftime("%H:%M"), lang, mode, int(conf) if conf.isdigit() else 90))
        conn.commit()
        conn.close()

        return jsonify({"proposed": proposed, "reason": reason, "confidence": conf, "verified": verified})
    except Exception as e:
        print(f"Server Error: {e}")
        return jsonify({"proposed": code, "reason": "System Latency", "confidence": 0, "verified": False})

@app.route('/upload_code', methods=['POST'])
def upload():
    file = request.files['file']
    return jsonify({"content": file.read().decode('utf-8', errors='ignore')})

if __name__ == '__main__':
    print("🚀 SREHEALER CORE ONLINE")
    app.run(port=5000)