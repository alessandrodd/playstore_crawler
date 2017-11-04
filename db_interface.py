import logging
import time

import pymongo
from pymongo.errors import BulkWriteError
from retry_decorator import retry

from config import conf, dbconf

PLAYSTORE_COLLECTION_NAME = "playstore"
CRAWLQUEUE_COLLECTION_NAME = "crawler_queue"

# configure remote dump location
client = pymongo.MongoClient(dbconf.address, int(dbconf.port), username=dbconf.user, password=dbconf.password)
db = client[dbconf.name]
playstore_col = db[PLAYSTORE_COLLECTION_NAME]
# for a given device and a given version code, an app should be unique
playstore_col.create_index(
    [("docid", pymongo.DESCENDING), ("details.appDetails.versionCode", pymongo.DESCENDING),
     ("device", pymongo.DESCENDING)], unique=True)
# ensure high performance for undownloaded apk retrieval
playstore_col.create_index([("download_start_time", pymongo.ASCENDING), ("offer.micros", pymongo.ASCENDING)])
crawlqueue_col = db[CRAWLQUEUE_COLLECTION_NAME]
# these index ensure high performance for the crawling scheduling operations
crawlqueue_col.create_index([("data", pymongo.DESCENDING), ("task", pymongo.DESCENDING)], unique=True)
crawlqueue_col.create_index([("start_time", pymongo.ASCENDING)])
crawlqueue_col.create_index([("start_time", pymongo.ASCENDING), ("end_time", pymongo.ASCENDING)])


@retry(pymongo.errors.AutoReconnect, tries=5, timeout_secs=1)
def dump_to_mongodb(entries, target_collection):
    """
    Dumps the entries to a given mongodb collection

    :param entries: collection of objects to dump
    :param target_collection: name of the collection where to save the entries
    """
    if not entries:
        return
    try:
        target_collection.insert_many(entries, False)
    except BulkWriteError as bwe:
        for err in bwe.details['writeErrors']:
            if int(err['code']) == 11000:
                # duplicate key, don't care
                pass
            else:
                logging.error(err['errmsg'])


def dump(entries):
    dump_to_mongodb(entries, playstore_col)


@retry(pymongo.errors.AutoReconnect, tries=5, timeout_secs=1)
def set_similar_apps(target_package, packages):
    update_result = playstore_col.update_many({'docid': target_package}, {"$set": {"similarTo": packages}})
    if not update_result or not update_result.matched_count:
        logging.error("Unable to set similar packages for {0}! Entry not found.".format(target_package))


@retry(pymongo.errors.AutoReconnect, tries=5, timeout_secs=1)
def enqueue_crawl_tasks(crawl_tasks):
    dump_to_mongodb(crawl_tasks, crawlqueue_col)


@retry(pymongo.errors.AutoReconnect, tries=5, timeout_secs=1)
def get_crawl_task():
    # get the first not-enqueued crawl task
    document_before = crawlqueue_col.find_one_and_update({"start_time": None}, {"$set": {"start_time": time.time()}},
                                                         sort=[('priority', pymongo.DESCENDING)])
    if not document_before:
        # if there isn't any task to do, check if there is an old task that has expired
        # (i.e. was started but never finished)
        task_max_duration = int(conf.max_task_duration_seconds)
        task_deadline = time.time() - task_max_duration
        document_before = crawlqueue_col.find_one_and_update({"start_time": {"$lt": task_deadline}, "end_time": None},
                                                             {"$set": {"start_time": time.time()}})
    return document_before


@retry(pymongo.errors.AutoReconnect, tries=5, timeout_secs=1)
def set_crawl_task_completed(task_id, error):
    if error:
        updated_doc = {"$set": {"end_time": time.time(), "error": error}}
    else:
        updated_doc = {"$set": {"end_time": time.time()}}
    document_before = crawlqueue_col.find_one_and_update({'_id': task_id}, updated_doc)
    if not document_before:
        logging.error("Unable to set task {0} as completed! Id not found.".format(task_id))


@retry(pymongo.errors.AutoReconnect, tries=5, timeout_secs=1)
def reset_crawl_task(task_id):
    document_before = crawlqueue_col.find_one_and_update({'_id': task_id},
                                                         {"$unset": {"start_time": "", "end_time": ""}})
    if not document_before:
        logging.error("Unable to set task {0} as completed! Id not found.".format(task_id))


@retry(pymongo.errors.AutoReconnect, tries=5, timeout_secs=1)
def set_crawl_task_priority(task_type, datas, priority):
    update_result = crawlqueue_col.update_many({"task": task_type, "data": {"$in": datas}},
                                               {"$set": {"priority": priority}})
    if not update_result or not update_result.matched_count:
        logging.error("Unable to set priority for {0}! Entry not found.".format(datas))


@retry(pymongo.errors.AutoReconnect, tries=5, timeout_secs=1)
def get_app_undownloaded(free_only=True):
    fil = {"download_start_time": None}
    if free_only:
        fil["offer"] = {"$elemMatch": {"micros": "0"}}
    document_before = playstore_col.find_one_and_update(fil, {"$set": {"download_start_time": time.time()}})
    if not document_before:
        # if there isn't any analysis to do, check if there is an old analysis that has expired
        # (i.e. was started but never finished)
        analysis_max_duration = int(conf.max_download_duration_seconds)
        analysis_deadline = time.time() - analysis_max_duration
        fil = {"download_start_time": {"$lt": analysis_deadline}, "download_end_time": None}
        if free_only:
            fil["offer"] = {"$elemMatch": {"micros": "0"}}
        document_before = playstore_col.find_one_and_update(fil, {"$set": {"download_start_time": time.time()}})
    return document_before


@retry(pymongo.errors.AutoReconnect, tries=5, timeout_secs=1)
def set_app_downloaded(app_id):
    document_before = playstore_col.find_one_and_update({'_id': app_id},
                                                        {"$set": {"download_end_time": time.time()}})
    if not document_before:
        logging.error("Unable to set app {0} as downloaded! Id not found.".format(app_id))


@retry(pymongo.errors.AutoReconnect, tries=5, timeout_secs=1)
def reset_app_download(app_id):
    document_before = playstore_col.find_one_and_update({'_id': app_id},
                                                        {"$unset": {"download_start_time": "",
                                                                    "download_end_time": ""}})
    if not document_before:
        logging.error("Unable to set app {0} as downloaded! Id not found.".format(app_id))
