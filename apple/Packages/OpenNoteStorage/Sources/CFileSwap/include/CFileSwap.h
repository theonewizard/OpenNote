#ifndef OPENNOTE_CFILESWAP_H
#define OPENNOTE_CFILESWAP_H

/// Swap two existing paths in one step (Linux renameat2 RENAME_EXCHANGE, Darwin renamex_np
/// RENAME_SWAP). Returns 0, or -1 with errno set; ENOTSUP/EINVAL mean the filesystem cannot.
int opennote_exchange(const char *from, const char *to);

/// Rename `from` to `to` only if `to` does not exist (RENAME_NOREPLACE / RENAME_EXCL).
int opennote_rename_noreplace(const char *from, const char *to);

/// Flush a file descriptor to stable storage: F_FULLFSYNC on Darwin, fsync elsewhere.
int opennote_full_fsync(int fd);

#endif
