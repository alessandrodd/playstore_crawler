from enum import Enum


class CrawlTask(Enum):
    """
    Represents a task (job) that should be executed by the crawler,
    i.e. "SIMILAR" task means that the crawler should find all the
    packages similar to the given one
    """
    SIMILAR = "CRAWL_SIMILAR"
    CREATOR = "CRAWL_CREATOR"
    DETAILS = "CRAWL_DETAILS"

    def __str__(self):
        return str(self.value)
