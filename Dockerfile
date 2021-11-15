FROM tiangolo/uvicorn-gunicorn-fastapi:python3.8
RUN pip install --upgrade pip
RUN groupadd -g 999 wittyuser && \
    useradd --create-home -r -u 999 -g wittyuser wittyuser
USER wittyuser
WORKDIR /home/wittyuser
ENV APP_MODULE=app.main:app
ENV LANGUAGETOOL_API=https://lt.api.witty.works/v2 
ENV WORKERS=6
COPY --chown=wittyuser:wittyuser requirements.txt requirements.txt
ENV PATH="/home/wittyuser/.local/bin:${PATH}"
RUN pip install -r requirements.txt --user
RUN mkdir files
RUN spacy download en_core_web_sm
RUN spacy download de_core_news_sm
COPY --chown=wittyuser:wittyuser . .
CMD gunicorn app.main:app -b 0.0.0.0:8000 -w $WORKERS -k uvicorn.workers.UvicornWorker --forwarded-allow-ips="*"

