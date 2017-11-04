import os


def get_folder_size(dir_path):
    """
    Computes folder size (all files and-subfolders size)

    :param dir_path: path of the folder
    :return: total size of the folder
    :rtype int
    """
    total_size = 0
    d = os.scandir(dir_path)
    for entry in d:
        try:
            if entry.is_dir():
                total_size += get_folder_size(entry.path)
            else:
                total_size += entry.stat().st_size
        except FileNotFoundError:
            # file was deleted during scan
            pass
    return total_size


def sanitize_filename(filename):
    """
    Removes illegal characters from a string in order to obtain
    a valid file name

    :param filename: non-sanitized filename
    :return: sanitized filename
    :rtype: str
    """
    keep_characters = (' ', '.', '_')
    return "".join(c for c in filename if c.isalnum() or c in keep_characters).rstrip()
