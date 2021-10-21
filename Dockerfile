FROM tiangolo/uvicorn-gunicorn-fastapi:python3.8
ENV APP_MODULE=app.main:app
RUN mkdir files
COPY requirements.txt /app
RUN pip install --upgrade pip && \
    pip install -r /app/requirements.txt
RUN python3.8 -m spacy download en_core_web_sm
RUN python3.8 -m spacy download de_core_news_sm
COPY ./ /app
CMD pybabel compile -d locales -l de_DE -f
CMD pybabel compile -d locales -l en_GB -f
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0" ,"--port" ,"8000"]
