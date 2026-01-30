from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import os
import json
from docx import Document
from PyPDF2 import PdfReader
import google.generativeai as genai

app = Flask(__name__)
app.secret_key = 'supersecretkey'

app.jinja_env.globals.update(enumerate=enumerate)

# Configure Gemini API
genai.configure(api_key="AIzaSyDmaAU3JOtYTyQO_j6Sd_eBrkn5TqlRCwQ")
model = genai.GenerativeModel("gemini-1.5-flash")

# Authentication JSON file
USER_DATA_FILE = 'users.json'

# Ensure the JSON file exists
if not os.path.exists(USER_DATA_FILE):
    with open(USER_DATA_FILE, 'w') as f:
        json.dump({}, f)


@app.route('/')
def login_signup():
    """Render login/signup page."""
    if 'username' in session:
        return redirect(url_for('form_page'))
    return render_template('login.html')


@app.route('/authenticate', methods=['POST'])
def authenticate():
    """Handle login or signup."""
    username = request.form['username']
    password = request.form['password']
    action = request.form['action']

    with open(USER_DATA_FILE, 'r') as f:
        users = json.load(f)

    if action == 'login':
        if username in users and users[username] == password:
            session['username'] = username
            return redirect(url_for('form_page'))
        else:
            return render_template('login.html', error="Invalid username or password.")
    elif action == 'signup':
        if username in users:
            return render_template('login.html', error="Username already exists.")
        else:
            users[username] = password
            with open(USER_DATA_FILE, 'w') as f:
                json.dump(users, f)
            session['username'] = username
            return redirect(url_for('form_page'))


@app.route('/logout')
def logout():
    """Logout user."""
    session.pop('username', None)
    return redirect(url_for('login_signup'))


@app.route('/form')
def form_page():
    """Render form page."""
    if 'username' not in session:
        return redirect(url_for('login_signup'))
    return render_template('form.html')


@app.route('/generate', methods=['POST'])
def generate():
    """Generate MCQs and display them."""
    if 'username' not in session:
        return redirect(url_for('login_signup'))

    document = request.files['document']
    num_questions = int(request.form['numQuestions'])
    difficulty = request.form['difficulty']

    # Extract text
    extracted_text = extract_text_from_document(document)
    if not extracted_text:
        return render_template('form.html', error="Could not extract text from file. Please try another document.")

    # Generate MCQs
    mcqs = generate_mcqs_from_text(extracted_text, num_questions, difficulty)
    
    if not mcqs:
        return render_template('form.html', error="Failed to generate MCQs. Try again.")

    session['mcqs'] = mcqs
    session['score'] = 0  # Reset score

    return redirect(url_for('display_questions'))


@app.route('/questions')
def display_questions():
    """Display MCQs."""
    if 'username' not in session:
        return redirect(url_for('login_signup'))

    mcqs = session.get('mcqs', [])
    return render_template('questions.html', mcqs=mcqs)


@app.route('/submit_answers', methods=['POST'])
def submit_answers():
    """Process answers and calculate score."""
    if 'username' not in session:
        return redirect(url_for('login_signup'))

    mcqs = session.get('mcqs', [])
    user_answers = request.form.to_dict()

    print("🔍 Debug: User Answers:", user_answers)  # Print submitted answers
    print("🔍 Debug: MCQs Stored in Session:", mcqs)  # Print stored MCQs

    score = 0
    for i, mcq in enumerate(mcqs):
        correct_option = mcq["correctOption"]  # This is an integer
        user_choice = user_answers.get(f'answer_{i}', "-1")  # Default to "-1" if missing

        try:
            if int(user_choice) == correct_option:  # Convert user input to integer before comparison
                score += 1
        except ValueError:
            print(f"⚠️ Invalid answer format for question {i}: {user_choice}")  # Debugging

    session['score'] = score  # Ensure session updates
    session.modified = True  # Force session update

    print(f"✅ Final Score Calculated: {score}")  # Debugging output

    return redirect(url_for('feedback'))



@app.route('/feedback')
def feedback():
    """Render feedback page."""
    if 'username' not in session:
        return redirect(url_for('login_signup'))

    session.modified = True  # Force session update
    score = session.get('score', 0)
    mcqs = session.get('mcqs', [])

    print(f"🔄 Fetching Score for Feedback: {score}/{len(mcqs)}")  # Debugging output

    return render_template('feedback.html', score=score, total=len(mcqs))

@app.route('/submit_feedback', methods=['POST'])
def submit_feedback():
    """Handle user feedback on question difficulty."""
    if 'username' not in session:
        return redirect(url_for('login_signup'))

    difficulty_feedback = request.form['difficulty_feedback']
    username = session['username']

    # Save feedback to a file or database
    feedback_data = {
        'username': username,
        'difficulty_feedback': difficulty_feedback,
    }

    # Append feedback to a JSON file
    FEEDBACK_FILE = 'feedback.json'
    if not os.path.exists(FEEDBACK_FILE):
        with open(FEEDBACK_FILE, 'w') as f:
            json.dump([], f)

    with open(FEEDBACK_FILE, 'r') as f:
        feedback_list = json.load(f)

    feedback_list.append(feedback_data)

    with open(FEEDBACK_FILE, 'w') as f:
        json.dump(feedback_list, f)

    return redirect(url_for('feedback'))


def extract_text_from_document(document):
    """Extract text from uploaded document."""
    try:
        if document.filename.endswith('.pdf'):
            reader = PdfReader(document)
            return ' '.join(page.extract_text() or '' for page in reader.pages)
        elif document.filename.endswith('.docx'):
            doc = Document(document)
            return ' '.join(para.text for para in doc.paragraphs)
        else:
            return None
    except Exception as e:
        print(f"Error extracting text: {e}")
        return None


def generate_mcqs_from_text(text, num_questions, difficulty):
    """Generate unique MCQs using Gemini API."""
    generated_questions = set()
    mcqs = []

    prompt = (
        f"Generate {num_questions} UNIQUE {difficulty}-level multiple-choice questions from the following text.\n"
        "Ensure each question has exactly 4 options with one correct answer.\n"
        "DO NOT REPEAT OR DUPLICATE QUESTIONS. Format the response as follows:\n\n"
        "Question: <your question>\n"
        "A) <option 1>\n"
        "B) <option 2>\n"
        "C) <option 3>\n"
        "D) <option 4> (Correct)\n\n"
        f"Text:\n{text[:5000]}"  # Truncate to avoid token limits
    )

    try:
        response = model.generate_content(prompt)
        response_text = response.text.strip()
        mcq_list = response_text.split("\n\n")

        for mcq_text in mcq_list:
            mcq_data = parse_mcq_response(mcq_text)
            if mcq_data and mcq_data['question'] not in generated_questions:
                mcqs.append(mcq_data)
                generated_questions.add(mcq_data['question'])

            if len(mcqs) >= num_questions:
                break

    except Exception as e:
        print(f"Error generating MCQs: {e}")
    
    return mcqs


def parse_mcq_response(response_text):
    """Parse generated response into structured MCQ data."""
    try:
        lines = [line.strip() for line in response_text.strip().split('\n') if line.strip()]
        if len(lines) < 5:
            return None  # Ensure we have a question + 4 options

        question = lines[0].replace("Question:", "").strip()
        options = [line[3:].strip() for line in lines[1:5]]  # Remove "A) ", "B) ", etc.

        correct_option = next((i for i, opt in enumerate(options) if "(Correct)" in opt), None)
        if correct_option is None:
            return None  # Skip if no correct option found

        options[correct_option] = options[correct_option].replace("(Correct)", "").strip()
        
        return {"question": question, "options": options, "correctOption": correct_option}

    except (IndexError, ValueError):
        return None


if __name__ == '__main__':
    app.run(debug=True)
