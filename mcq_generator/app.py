from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import os
import json
from docx import Document
from PyPDF2 import PdfReader
from openai import OpenAI

app = Flask(__name__)
app.secret_key = 'supersecretkey'

app.jinja_env.globals.update(enumerate=enumerate)  # Secret key for session management

client = OpenAI(api_key="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")
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

    # Load user data
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
    extracted_text = extract_text_from_document(document)[:5000]

    # Generate MCQs
    mcqs = generate_mcqs_from_text(extracted_text, num_questions, difficulty)
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
    session['answers'] = user_answers  # Save user answers in the session

    score = 0
    for i, mcq in enumerate(mcqs):
        if str(mcq['correctOption']) == user_answers.get(f'answer_{i}'):
            score += 1

    session['score'] = score
    return redirect(url_for('feedback'))


@app.route('/feedback')
def feedback():
    """Render feedback page."""
    if 'username' not in session:
        return redirect(url_for('login_signup'))

    score = session.get('score', 0)
    mcqs = session.get('mcqs', [])
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
    if document.filename.endswith('.pdf'):
        reader = PdfReader(document)
        return ''.join(page.extract_text() for page in reader.pages)
    elif document.filename.endswith('.docx'):
        doc = Document(document)
        return ' '.join(para.text for para in doc.paragraphs)
    else:
        raise ValueError("Unsupported file type. Please upload a PDF or DOCX file.")


def generate_mcqs_from_text(text, num_questions, difficulty):
    """Generate unique MCQs using GPT-4 Turbo."""
    generated_questions = set()
    mcqs = []
    while len(mcqs) < num_questions:
        prompt = (
            f"Generate a {difficulty} multiple-choice question from the following text. "
            f"Ensure the question is unique and includes 4 options with one correct answer labeled '(Correct)':\n\n"
            f"{text}\n\n"
            f"Do not repeat questions. Each question should be distinct and cover different aspects of the text."
        )
        response = client.chat.completions.create(
            model="gpt-4-turbo",  # Use GPT-4 Turbo
            messages=[
                {"role": "system", "content": "You are a helpful assistant that generates multiple-choice questions."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=1000,
        )
        mcq_text = response.choices[0].message.content.strip()
        mcq_data = parse_mcq_response(mcq_text)
        if mcq_data and mcq_data['question'] not in generated_questions:
            mcqs.append(mcq_data)
            generated_questions.add(mcq_data['question'])
        else:
            print("Duplicate or invalid question detected. Regenerating...")
    return mcqs


def parse_mcq_response(response_text):
    """Parse generated response into structured MCQ data."""
    try:
        lines = [line.strip() for line in response_text.strip().split('\n') if line.strip()]
        question = lines[0]
        options = lines[1:5]
        correct_option = None

        for i, option in enumerate(options):
            if '(Correct)' in option:
                correct_option = i
                options[i] = option.replace('(Correct)', '').strip()

        if correct_option is None or len(options) < 4:
            return None

        return {
            "question": question,
            "options": options,
            "correctOption": correct_option,
        }
    except (IndexError, ValueError):
        return None


if __name__ == '__main__':
    app.run(debug=True)