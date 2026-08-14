"""Server start karne ka simple entry point:  python run.py"""
import uvicorn

from app.config import PORT

if __name__ == "__main__":
    print(f"\n  Hiring Agent chal raha hai:  http://localhost:{PORT}\n")
    uvicorn.run("app.main:app", host="127.0.0.1", port=PORT, reload=False)
