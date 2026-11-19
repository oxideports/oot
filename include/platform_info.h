#ifndef PLATFORM_INFO_H
#define PLATFORM_INFO_H

#if defined(__BYTE_ORDER__) && defined(__ORDER_BIG_ENDIAN__)
#define IS_BIG_ENDIAN (__BYTE_ORDER__ == __ORDER_BIG_ENDIAN__)
#elif defined(PLATFORM_N64) && PLATFORM_N64
#define IS_BIG_ENDIAN 1
#else
#define IS_BIG_ENDIAN 0
#endif

#endif // PLATFORM_INFO_H
