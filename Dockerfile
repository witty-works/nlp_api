FROM python:3.11.1

# https://dev.to/mrpbennett/setting-up-docker-with-pipenv-3h1o

# Keeps Python from generating .pyc files in the container
ENV PYTHONDONTWRITEBYTECODE=1

# Turns off buffering for easier container logging
ENV PYTHONUNBUFFERED=1

# Install & use pipenv
RUN python -m pip install --upgrade pip
COPY requirements.txt requirements.txt
RUN pip install -r requirements.txt --user

RUN mkdir /code
WORKDIR /code

COPY ./app /code/app

COPY ./locales /code/locales

COPY ./training_data /code/training_data

# Creates a non-root user and adds permission to access the /code folder
RUN adduser -u 5678 --disabled-password --gecos "" appuser && chown -R appuser /code
USER appuser

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8081"]

EXPOSE 8081