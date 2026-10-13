FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY crm ./crm
RUN pip install --no-cache-dir . && useradd --create-home --uid 10001 crm
COPY app.py alembic.ini ./
COPY migrations ./migrations
COPY .streamlit/config.toml ./.streamlit/config.toml
USER crm
EXPOSE 8501
CMD ["python", "-m", "streamlit", "run", "app.py", "--server.address=0.0.0.0"]
