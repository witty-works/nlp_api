FROM tiangolo/uvicorn-gunicorn-fastapi:python3.9

# setup ssh for app service ssh connection
RUN apt-get update \
  && apt-get install -y openssh-server gosu \
  && echo "root:Docker!" | chpasswd

COPY ops/sshd_config /etc/ssh/
RUN mkdir -p /tmp
COPY ops/ssh_setup.sh /tmp
RUN chmod +x /tmp/ssh_setup.sh \
  && (sleep 1;/tmp/ssh_setup.sh 2>&1 > /dev/null)

# setup nlp api
RUN pip install --upgrade pip
RUN groupadd -g 999 wittyuser && \
  useradd --create-home -r -u 999 -g wittyuser wittyuser
USER wittyuser
WORKDIR /home/wittyuser
ENV APP_MODULE=app.main:app
# app service in azure allows access to containers via localhost
ENV LANGUAGETOOL_API=http://languagetool:8000/v2 
ENV WORKERS 6
ENV LOGGING_CONFIG_LEVEL ERROR
ENV TESTING True
COPY --chown=wittyuser:wittyuser requirements.txt requirements.txt
ENV PATH="/home/wittyuser/.local/bin:${PATH}"
RUN pip install -r requirements.txt --user
RUN mkdir files \
  && spacy download en_core_web_sm \
  && spacy download de_core_news_md
COPY --chown=wittyuser:wittyuser . .
RUN pybabel compile -d locales -l de_DE -f \
  && pybabel compile -d locales -l en_US -f
RUN wget -P training_data https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.bin
# azure app services needs port 80 or 8080 exposed
ENV PORT 8080
EXPOSE 8080 

USER root
# setup custom entrypoint to allow the start of sshd as root
# and the start of gunicorn as wittyuser
COPY ops/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
# app services need the port 2222 exposed for ssh access
EXPOSE 2222

CMD [ "/entrypoint.sh" ]
