FROM        ubuntu:latest
MAINTAINER  James Turk <james@openstates.org>

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    python2.7 \
    python-pip \
    python-lxml \
    libssl-dev \
    mdbtools \
    python-dev \
    python3-dev \
    poppler-utils \
    python-virtualenv \
    python3.5 \
    git \
    libpq-dev \
    libgeos-dev \
    s3cmd \
    freetds-dev \
    curl \
    wget \
    unzip \
    mysql-server \
    libmysqlclient-dev \
    mdbtools

RUN mkdir -p /opt/openstates/
RUN mkdir -p /var/run/mysqld/
RUN chown mysql /var/run/mysqld/

RUN virtualenv -p $(which python2) /opt/openstates/venv-billy/
RUN /opt/openstates/venv-billy/bin/pip install -e git+https://github.com/openstates/billy.git#egg=billy
RUN /opt/openstates/venv-billy/bin/pip install python-dateutil

RUN virtualenv -p $(which python3) /opt/openstates/venv-pupa/
RUN /opt/openstates/venv-pupa/bin/pip install -e git+https://github.com/opencivicdata/python-opencivicdata.git#egg=python-opencivicdata
RUN /opt/openstates/venv-pupa/bin/pip install -e git+https://github.com/opencivicdata/pupa.git#egg=pupa

ENV PYTHONIOENCODING 'utf-8'
ENV LANG 'en_US.UTF-8'
ENV LANGUAGE=en_US:en
ENV LC_ALL=C.UTF-8
ENV PYTHONDONTWRITEBYTECODE=1
ENV BILLY_ENV /opt/openstates/venv-billy/
ENV PUPA_ENV /opt/openstates/venv-pupa/

ADD . /opt/openstates/openstates
RUN /opt/openstates/venv-pupa/bin/pip install -r /opt/openstates/openstates/requirements.txt

WORKDIR /opt/openstates/openstates/
ENTRYPOINT [/opt/openstates/openstates/pupa-scrape.sh]
