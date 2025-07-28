FROM python:3.10-slim

WORKDIR /app

COPY . .

RUN pip install PyMuPDF langdetect

CMD ["python", "code1a.py"]
