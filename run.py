"""Server start karne ka simple entry point:  python run.py"""
import uvicorn

from app.config import HOST, PORT

if __name__ == "__main__":
    print(f"\n  Hiring Agent chal raha hai:  http://localhost:{PORT}\n")
    uvicorn.run("app.main:app", host=HOST, port=PORT, reload=False)
