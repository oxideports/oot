#ifndef STDLIB_H
#define STDLIB_H

typedef struct lldiv_t {
    long long quot;
    long long rem;
} lldiv_t;

typedef struct ldiv_t {
    long quot;
    long rem;
} ldiv_t;

ldiv_t ldiv(long num, long denom);
lldiv_t lldiv(long long num, long long denom);

#ifdef NO_SEGMENTED_MEMORY
// Host allocator, used only by the native build's system-arena setup (main.c) — the N64 build uses
// its own arena and never sees these.
#include <stddef.h>
void* malloc(size_t size);
void free(void* ptr);
#endif

#endif
