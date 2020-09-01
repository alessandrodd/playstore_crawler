# playstore_crawler
Python scalable Google Play Store crawler

A Python crawler that scans the Google Play Store for applications and saves any available information about each app on a MongoDB database.

For technical details, [check out my thesis (_Automatic extraction of API Keys from Android applications_) and, in particular, **Chapter 4 and 5** of the work.](https://goo.gl/uryZeA)

The library responsible for interfacing with the Google Play Store is [a standalone project](https://github.com/alessandrodd/googleplay_api).

## Requirements

- MongoDB 3.2+
- Python 3.5+
- Modules in requirements.txt (use pip3 to install)
```
pip3 install -r requirements.txt
```

## Installation

```bash
$ git clone --recursive https://github.com/alessandrodd/playstore_crawler.git
$ cd playstore_crawler
$ pip3 install -r requirements.txt
$ python3 main.py
```

A running MongoDB instance is needed to store the crawler results and task queue. Configure the mongodb object in the config.yml file with the required information.
You can use the following command in mongoshell to add an authorized user:

    db.createUser({user: "playstore_crawler", pwd: "alessandrodd", roles: [ { role: "dbOwner", db: "mytestdb" } ]})

You also need to rename the [config.example.yml](googleplay_api/googleplay_api/config.example.yml) file to config.yml and fill it with a proper Google Service Framework ID and either gmail credentials (google_login and google_password) or a subAuth token.
Alternatively, you can use the crawler with a [token dispenser](https://github.com/yeriomin/token-dispenser) specified through the token-dispenser argument.

## Usage

```bash
usage: main.py [-h] [--debug] [--initialize-db] [--crawl-playstore]
               [--token-dispenser DISPENSER_URL] [--apks-pool]
               [--output-dir OUT_DIR] [--output-dir-size MAX_DIR_SIZE]
               [--http-proxy HTTP_PROXY] [--https-proxy HTTPS_PROXY]
               [--change-priority CRAWLING_PACKAGES [CRAWLING_PACKAGES ...]]

A play store python crawler

optional arguments:
  -h, --help            show this help message and exit
  --debug               Print debug information
  --initialize-db       Initialize the DB with an initial set of apps
  --crawl-playstore     Crawl the playstore starting from an initialized
                        database
  --token-dispenser DISPENSER_URL
                        If a token dispenser should be used to retrieve
                        authentication tokens

  --apks-pool           Creates a pool of apks in the folder specified by
                        --output-dir. It downloads as many apks as possible
                        and stops as soon as the folder size defined by
                        --output-dir-size is exceeded. It monitors the output
                        folder until enough space is freed to download the
                        next apk.
  --output-dir OUT_DIR  Where to download apks
  --output-dir-size MAX_DIR_SIZE
                        Limit size for output dir (in megabytes)

  --http-proxy HTTP_PROXY
                        http proxy, ONLY used forPlay Store requests!
  --https-proxy HTTPS_PROXY
                        https proxy, ONLY used forPlay Store requests!

  --change-priority CRAWLING_PACKAGES [CRAWLING_PACKAGES ...]
                        Change priority to 10 for the given CRAWLING_PACKAGES
```


The crawling process is composed of two phases:
- Initialization Phase
- Crawling Phase

To initialize the database, run the playstore_crawler with the initialize-db parameter:

    python3 main.py --initialize-db

**The DB should be initialized once**, from a single crawler instance.
The initialization phase should take just a few minutes with a standard desktop computer and a 10MBit ADSL connection.

Once the initialization phase is completed, you can launch multiple instances of the crawler on any host, provided they are all configured with the same database.
However, please note that **the crawling speed is limited by the number of IP Addresses used**. In other words, to speed up the process, it is advisable to start one instance on each host that has a unique IP address or to use different proxy settings for each crawler instance.

To start the crawling process:

    python3 main.py --crawl-playstore

## Config File Explained
### config.json

**slow_crawl** => If false, the crawler uses the _similar apps_ endpoint to discover new apps. If true, it uses the _similar_, _preInstall_ and _postInstall_ relations to discover new apps. Please note that setting this parameter to "true" really slows the crawling operation. In both cases, the crawler also checks for apps developed from the same developer of each detected app.

**more_details** => If true, the crawler requests more information to the Play Store (e.g. the complete app description). Slows down the crawling operation a bit and takes up much more space on the DB.

**apks_pool_folder** => Default apks pool path for --apks-pool

**apks_pool_size_mb** => Default apks pool size (in MB) for --apks-pool

**max_task_duration_seconds** => Any crawling task that has started more than max_task_duration_seconds without being completed, is considered as failed and automatically re-scheduled.

**max_download_duration_seconds** => Any app downloaded started more than max_download_duration_seconds seconds ago and not finished, is considered as not download and can be downloaded when using the --apks-pool argument

**logging** => Used to config logging capabilities, see [here](https://docs.python.org/3/howto/logging.html)


### dbconfig.json

**name** => Name of the MongoDB 3.+ database

**address** => Address of the MongoDB 3.+ database

**port** => Port to which to contact the MongoDB 3.+ database (default 27017)

**user** => Database credentials

**password** => Database credentials

# Sample Data

For a **full Play Store crawling dump** and analysis, [check out this repository](https://github.com/alessandrodd/playstore_graph_analysis)
