#define _GNU_SOURCE
#include "CFileSwap.h"

#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <unistd.h>

#if defined(__APPLE__)

int opennote_exchange(const char *from, const char *to) {
    return renamex_np(from, to, RENAME_SWAP);
}

int opennote_rename_noreplace(const char *from, const char *to) {
    return renamex_np(from, to, RENAME_EXCL);
}

int opennote_full_fsync(int fd) {
    if (fcntl(fd, F_FULLFSYNC) == 0) {
        return 0;
    }
    return fsync(fd);  // filesystems without F_FULLFSYNC (network volumes)
}

#elif defined(__linux__)

#include <sys/syscall.h>
#ifndef RENAME_NOREPLACE
#define RENAME_NOREPLACE (1 << 0)
#endif
#ifndef RENAME_EXCHANGE
#define RENAME_EXCHANGE (1 << 1)
#endif

int opennote_exchange(const char *from, const char *to) {
    return (int)syscall(SYS_renameat2, AT_FDCWD, from, AT_FDCWD, to, RENAME_EXCHANGE);
}

int opennote_rename_noreplace(const char *from, const char *to) {
    return (int)syscall(SYS_renameat2, AT_FDCWD, from, AT_FDCWD, to, RENAME_NOREPLACE);
}

int opennote_full_fsync(int fd) {
    return fsync(fd);
}

#else

int opennote_exchange(const char *from, const char *to) {
    errno = ENOTSUP;
    return -1;
}

int opennote_rename_noreplace(const char *from, const char *to) {
    errno = ENOTSUP;
    return -1;
}

int opennote_full_fsync(int fd) {
    return fsync(fd);
}

#endif
