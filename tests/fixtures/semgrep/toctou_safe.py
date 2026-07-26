# negative: uses os.open with mode (safe)
import os
import stat


def save_data(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT, stat.S_IRUSR | stat.S_IWUSR)
    os.write(fd, data.encode())
    os.close(fd)
