FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --default-timeout=100 -r requirements.txt

COPY . .

CMD ["python", "code1a.py"]
