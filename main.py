"""
A Google Play Store crawler. Can be used to create a database containing information on all the
apps available on the Google Play Store.

Its operation is simple:
-First it retrieves a list of all the charts available for each category; e.g. "TOP PAID" in Games,
 "TRENDING" in "Food And Drinks" and so on.
-Then, all the apps in the charts are inserted in the database
-For each new app discovered, two tasks are scheduled:
 -One to find all the apps similar to the given app
 -Another one to find all the apps produced by the same developer (if it's the first time that it sees the
  above developer)
-Execute and submit new task until no more task are available

In simple terms, it goes from one app to 0 or more other apps following the similarity-edge until no more
new apps are discovered.

"""
import argparse
import json
import logging
import os
import time
from logging.config import dictConfig
from urllib.parse import urlparse, parse_qs

import requests
from google.protobuf import json_format

LOG_CONFIG_PATH = "log_config.json"
__location__ = os.path.realpath(os.path.join(os.getcwd(), os.path.dirname(__file__)))

import config

with open(os.path.join(__location__, LOG_CONFIG_PATH), "r", encoding="utf-8") as fd:
    log_config = json.load(fd)
    logging.config.dictConfig(log_config["logging"])

from my_model.crawl_task import CrawlTask
from my_tools.file_tools import get_folder_size, sanitize_filename

import db_interface

from googleplay_api.googleplay_api.googleplay import GooglePlayAPI, DownloadError, RequestError
import googleplay_api.googleplay_api.config as play_conf

emulated_device = play_conf.get_option("device")
play_store = None


def get_all_subcategories():
    """
    Python generator to retrieve Google Play Store categories

    :return: all the (category, subcategory) pairs available on playstore
    :rtype: (str, str)
    """
    categories = play_store.browse()
    for category in categories.category:
        o = urlparse(category.dataUrl)
        query = parse_qs(o.query)
        cat_id = query['cat'][0]
        subcategories = play_store.browse(cat=cat_id)
        if len(subcategories.category) > 0:
            for subcategory in subcategories.category:
                o = urlparse(subcategory.dataUrl)
                query = parse_qs(o.query)
                cat_id = query['cat'][0]
                tabs = play_store.list(cat=cat_id)
                for doc in tabs.doc:
                    yield cat_id, doc.docid
        else:
            tabs = play_store.list(cat=cat_id)
            for doc in tabs.doc:
                yield cat_id, doc.docid


def dump_data(bulk_details):
    """
    Dumps the data retrieved from bulk_details requests to the configured location
    and schedules the new crawling tasks

    :param bulk_details: data retrieved from bulk_details requests
    """
    entries = []
    crawl_tasks = []
    for entry in bulk_details.entry:
        json_entry = json.loads(json_format.MessageToJson(entry.doc))
        json_entry['device'] = emulated_device
        entries.append(json_entry)
        crawl_tasks.append({"data": entry.doc.creator, "task": CrawlTask.CREATOR.value})
        crawl_tasks.append({"data": entry.doc.docid, "task": CrawlTask.SIMILAR.value})
    db_interface.dump(entries)
    db_interface.enqueue_crawl_tasks(crawl_tasks)


def dump_data_details(details):
    """
    Dumps the data retrieved from details requests to the configured location
    and schedules the new crawling tasks

    :param details: data retrieved from details requests
    """
    packages_found = []
    if "similar" in details:
        packages_found += details["similar"]
    if "preInstall" in details:
        packages_found += details["preInstall"]
    if "postInstall" in details:
        packages_found += details["postInstall"]
    crawl_tasks = [{"data": details["creator"], "task": CrawlTask.CREATOR.value}]
    for package in packages_found:
        crawl_tasks.append({"data": package, "task": CrawlTask.DETAILS.value})
    details['device'] = emulated_device
    db_interface.dump([details])
    db_interface.enqueue_crawl_tasks(crawl_tasks)


def initialize_database():
    """
    Initializes the Google Play Store crawl database with an initial set of data;
    this set is composed of the apps appearing in the category charts (e.g. TOP FREE, TOP PAID...)
    """
    for cat_id, tab in get_all_subcategories():
        logging.info("Scraping {0} => {1}".format(cat_id, tab))
        list_result = play_store.list(cat_id, tab, maxResults=100)
        if config.slow_crawl:
            details = play_store.getPages(list_result, maxPages=None, details=True, includeChildDocs=config.more_details,
                                          includeDetails=config.more_details)
            dump_data(details)
        else:
            list_results = play_store.getPages(list_result, maxPages=None)
            crawl_tasks = []
            for doc in list_results.doc:
                for child in doc.child:
                    crawl_tasks.append({"data": child.docid, "task": CrawlTask.DETAILS.value})
            db_interface.enqueue_crawl_tasks(crawl_tasks)


def crawl_similar(package):
    list_result = play_store.listSimilar(package, maxResults=100)
    details = play_store.getPages(list_result, maxPages=None, details=True, includeChildDocs=config.more_details,
                                  includeDetails=config.more_details)
    similar_packages = []
    for entry in details.entry:
        similar_packages.append(entry.doc.docid)
    db_interface.set_similar_apps(package, similar_packages)
    dump_data(details)


def crawl_creator(creator):
    search_result = play_store.search(creator)
    details = play_store.getPages(search_result, maxPages=None, details=True, includeChildDocs=config.more_details,
                                  includeDetails=config.more_details)
    dump_data(details)


def crawl_details(package):
    details_result, pref_pages = play_store.details(package, True)
    details = json_format.MessageToDict(details_result)
    details = details["docV2"]
    details["similar"] = []
    details["preInstall"] = []
    details["postInstall"] = []

    similar = pref_pages.get("similar", None)
    if similar:
        similar = play_store.getPages(similar, alterMaxResults=100)
        for doc in similar.doc:
            for child in doc.child:
                details["similar"].append(child.docid)

    pre_install = pref_pages.get("preInstall", None)
    if pre_install:
        pre_install = play_store.getPages(pre_install, alterMaxResults=100)
        for doc in pre_install.doc:
            for child in doc.child:
                details["preInstall"].append(child.docid)

    post_install = pref_pages.get("postInstall", None)
    if post_install:
        post_install = play_store.getPages(post_install, alterMaxResults=100)
        for doc in post_install.doc:
            for child in doc.child:
                details["postInstall"].append(child.docid)

    dump_data_details(details)


def execute_crawl_task(task_type, task_data):
    switcher = {
        CrawlTask.SIMILAR.value: crawl_similar,
        CrawlTask.CREATOR.value: crawl_creator,
        CrawlTask.DETAILS.value: crawl_details
    }
    # Get the function from switcher dictionary
    func = switcher.get(task_type, lambda x: logging.warning("Unknown crawl task: " + str(task_type)))
    # Execute the function
    return func(task_data)


def crawl_playstore():
    """
    Play Store crawler's main loop; needs an initialized database (execute initialize_database() first)

    Picks an unexecuted crawl task and executes it.
    """
    while True:
        task = None
        try:
            task = db_interface.get_crawl_task()
            if not task:
                logging.info("No crawl task found! Exiting...")
                break
            task_id = task.get('_id')
            task_type = task.get('task')
            task_data = task.get('data')
            logging.info("Processing task {0} for {1}".format(task_type, task_data))
            error = None
            try:
                execute_crawl_task(task_type, task_data)
            except RequestError as e:
                error = e.http_status
            db_interface.set_crawl_task_completed(task_id, error)
        except KeyboardInterrupt:
            print('\nInterrupted! Reverting state...')
            if task:
                task_id = task.get('_id')
                db_interface.reset_crawl_task(task_id)
            break


def download_apk(package, version_code, output_path):
    """
    :param package: app's package, e.g. com.android.chrome
    :param version_code: which version of the app you want to download
    :param output_path: where to save the apk file
    """
    try:
        # warning: we must emulate an ATOMIC write to avoid unfinished files.
        # To do so, we use the os.rename() function that should always be atomic under
        # certain conditions (https://linux.die.net/man/2/rename)
        data = play_store.download(package, version_code)
        if not data:
            return
        with open(output_path + ".temp", "wb") as f:
            f.write(data)
        os.rename(output_path + ".temp", output_path)
    except DownloadError as e:
        logging.error(str(e))


def create_apks_pool(output_dir, dir_size):
    """
    Creates a pool of apks in the folder specified by output_dir
    It downloads as many apks as possible and stops as soon as the folder size
    defined by dir_size  is exceeded. It monitors the output folder until enough
    space is freed to download the next apk.

    :param output_dir: where to save downloaded apks
    :param dir_size: target directory size
    """
    if not os.path.exists(output_dir):
        os.mkdir(output_dir)
    while True:
        next_apk = None
        try:
            cur_size = get_folder_size(output_dir)
            if cur_size < dir_size * 1000 * 1000:
                next_apk = db_interface.get_app_undownloaded()
                if not next_apk:
                    print("No apk remaining! Shutting down.")
                    return
                app_id = next_apk.get('_id')
                docid = next_apk.get('docid')
                version_code = next_apk.get('details').get('appDetails').get('versionCode')
                filename = "{0}##{1}##{2}.apk".format(docid, version_code, str(app_id))
                filename = sanitize_filename(filename)
                output_path = os.path.join(output_dir, filename)
                while True:
                    try:
                        logging.info("Downloading {0}, Version {1}".format(docid, version_code))
                        download_apk(docid, version_code, output_path)
                        break
                    except IOError as e:
                        logging.error("Error while writing {0} : {1}".format(filename, e))
                db_interface.set_app_downloaded(next_apk.get('_id'))
            else:
                time.sleep(1)
        except KeyboardInterrupt:
            print('\nInterrupted! Reverting state...')
            if next_apk:
                app_id = next_apk.get('_id')
                db_interface.reset_app_download(app_id)
            break


def increase_priority(packages, priority=10):
    db_interface.set_crawl_task_priority(CrawlTask.DETAILS.value, packages, priority)


def main():
    parser = argparse.ArgumentParser(
        description='A play store python crawler', add_help=True
    )
    parser.add_argument('--debug', action="store_true", dest='boolean_debug',
                        default=False, help='Print debug information')
    parser.add_argument('--initialize-db', action="store_true", dest='boolean_init',
                        default=False, help='Initialize the DB with an initial set of apps')
    parser.add_argument('--crawl-playstore', action="store_true", dest='boolean_crawl',
                        default=False, help='Crawl the playstore starting from an initialized database')
    parser.add_argument('--token-dispenser', action="store", dest='dispenser_url', help='If a token dispenser should be'
                                                                                        ' used to retrieve '
                                                                                        'authentication tokens')
    group = parser.add_argument_group()
    group.add_argument('--apks-pool', action="store_true", dest='boolean_apkspool',
                       default=False, help='Creates a pool of apks in the folder specified by --output-dir. '
                                           'It downloads as many apks as possible and stops as soon as the folder size '
                                           'defined by --output-dir-size  is exceeded. It monitors '
                                           'the output folder until enough space is freed to download the next apk.')
    group.add_argument('--output-dir', action="store", dest='out_dir', help='Where to download apks')
    group.add_argument('--output-dir-size', action="store", dest='max_dir_size',
                       help='Limit size for output dir (in megabytes)')
    group_proxy = parser.add_argument_group()
    group_proxy.add_argument('--http-proxy', action="store", dest='http_proxy', help='http proxy, ONLY used for'
                                                                                     'Play Store requests!')
    group_proxy.add_argument('--https-proxy', action="store", dest='https_proxy', help='https proxy, ONLY used for'
                                                                                       'Play Store requests!')
    group_crawl_queue = parser.add_argument_group()
    group_crawl_queue.add_argument('--change-priority', action="store", dest='crawling_packages', nargs='+', type=str,
                                   help='Change priority to 10 for the given CRAWLING_PACKAGES')

    results = parser.parse_args()

    if results.boolean_debug:
        logging.basicConfig(level=logging.DEBUG)
    proxies = None
    if results.http_proxy:
        if proxies is None:
            proxies = {}
        proxies["http"] = results.http_proxy
    if results.https_proxy:
        if proxies is None:
            proxies = {}
        proxies["https"] = results.https_proxy
    global play_store
    play_store = GooglePlayAPI(throttle=True, proxies=proxies, errorRetryTimeout=0.1)
    token = None
    if results.dispenser_url:
        while True:
            response = requests.get(results.dispenser_url)
            token = response.text
            if response.status_code != 200 or len(token) != 71:
                logging.warning(
                    "HTTP Code: {0}; Invalid auth token: {1}. Retrying...".format(response.status_code, token))
            else:
                break
        logging.info("Using auth token: {0}".format(token))
    play_store.login(authSubToken=token)
    if results.boolean_init:
        initialize_database()
        return
    if results.boolean_crawl:
        crawl_playstore()
        return
    if results.boolean_apkspool:
        out_dir = results.out_dir
        if not out_dir:
            out_dir = config.apks_pool_folder
        dir_size = results.max_dir_size
        if not dir_size:
            dir_size = config.apks_pool_size_mb
        create_apks_pool(os.path.abspath(out_dir), dir_size)
        return

    if results.crawling_packages:
        increase_priority(results.crawling_packages)
        return

    parser.print_help()


if __name__ == '__main__':
    main()
