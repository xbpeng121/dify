import datetime
import time

import click
from werkzeug.exceptions import NotFound

import app
from configs import dify_config
from extensions.ext_database import db
from models.model import UploadFile
from services.file_service import FileService


@app.celery.task(queue="dataset")
def clean_temporary_upload_files_task():
    click.echo(click.style("Start clean temporary upload files.", fg="green"))
    start_at = time.perf_counter()
    plan_clean_temporary_upload_files_day = datetime.datetime.now() - datetime.timedelta(
        days=dify_config.CLEAN_UPLOAD_TEMPORARY_FILE_DAY_SETTING
    )
    while True:
        try:
            upload_files = (
                db.session.query(UploadFile)
                .filter(UploadFile.is_temporary == True)
                .filter(UploadFile.created_at < plan_clean_temporary_upload_files_day)
                .order_by(UploadFile.created_at.desc())
                .limit(100)
                .all()
                )
        except NotFound:
            break
        if not upload_files:
            break
        for file in upload_files:
            FileService.delete_file(file_key=file.key)
    end_at = time.perf_counter()
    click.echo(click.style("Cleaned temporary upload files from db+storage success latency: {}"
                           .format(end_at - start_at), fg="green"))
    
