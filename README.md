# DeepSeek-Chat-WebApp
 Conversational AI Web App with NiceGUI, FastAPI, and Fine-tuned DeepSeek Model.

A full-stack web application demonstrating how to build a ChatGPT/Gemini-like conversational interface using Python. This project features:

*   **Frontend:** UI built with **NiceGUI**.
*   **Backend:** An asynchronous API with **FastAPI**.
*   **Database:** User data and chat history stored in **PostgreSQL**.
*   **LLM Integration:** Real-time, streaming responses from a locally hosted, fine-tuned Small Language Model (SLM) **DeepSeek-R1-Distill-Qwen-1.5B**.

**Note:** This repository serves as a practical example for integrating modern Python web frameworks with custom AI models for interactive applications.

## Technology Stack

*   **Frontend Framework:** [NiceGUI](https://nicegui.io/)
*   **Backend Framework:** [FastAPI](https://fastapi.tiangolo.com/)
*   **Database:** [PostgreSQL](https://www.postgresql.org/)
*   **ORM:** [SQLAlchemy](https://www.sqlalchemy.org/) (asyncio with asyncpg)
*   **LLM Interaction:** [Hugging Face Transformers](https://huggingface.co/docs/transformers/index), [PEFT](https://huggingface.co/docs/peft/index), [Accelerate](https://huggingface.co/docs/accelerate/index), [PyTorch](https://pytorch.org/)
*   **Password Hashing:** [Passlib](https://passlib.readthedocs.io/en/stable/) (with bcrypt)
*   **Web Server:** [Uvicorn](https://www.uvicorn.org/)
*   **Language:** Python 3.8+