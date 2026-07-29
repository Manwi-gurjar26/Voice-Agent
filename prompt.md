Act as an Expert SaaS Architect and Senior Full-Stack Developer. 

I am building a comprehensive SaaS project: a platform where clients can generate an embeddable URL (a <script> tag) to add an AI-powered voice agent and text chatbot to their own websites. 

I am an AI engineer with a strong background in data analytics, machine learning models, and Python. I am very comfortable handling the backend AI pipelines, LLM integration, and data processing. However, I need your expert architectural guidance and code for the full-stack infrastructure, specifically the lightweight frontend embedding and the SaaS client dashboard.

Here is the planned architecture:

1. The Embeddable Widget (Client-Side):
- A highly lightweight, vanilla JavaScript (or Preact/Svelte) script that injects a floating chat UI into the host website.
- Must handle text input and microphone permissions for voice capabilities.
- Must be extremely fast and not impact the host website's load time.

2. The AI Engine & Backend (API Layer):
- Python (FastAPI) to handle the core logic.
- Integrations for STT (Speech-to-Text), an LLM, and TTS (Text-to-Speech).
- RAG (Retrieval-Augmented Generation) infrastructure so clients can upload their own business data/website URLs to train their specific agent.

3. The Admin Dashboard (SaaS Platform):
- A frontend (React/Next.js) for clients to sign up, configure their chatbot, upload knowledge base documents, and copy their unique embed script.
- A database (PostgreSQL) to store client configurations, API limits, and conversation logs.

Here is how we will work together:
I want this project built properly and robustly, step-by-step. Do not generate the entire codebase at once, but rather follow an autonomous, self-correcting workflow.

1. First, provide a high-level roadmap of the development phases.
2. Provide the instructions, file structure, and code for ONLY the current step.
3. Once you write the code for a step, YOU must autonomously review and mentally dry-run your own code. It is your job to check for any problems, bugs, security flaws, or missing logic.
4. If you identify any issues during your review, you must solve the problem immediately and provide the corrected code.
5. Once you have verified the code is flawless and functioning correctly, output the final code for that step, and then automatically proceed to the next step in the roadmap.

Please begin with the roadmap and your self-reviewed code for Step 1.