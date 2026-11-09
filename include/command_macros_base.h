#ifndef COMMAND_MACROS_BASE_H
#define COMMAND_MACROS_BASE_H

#include "platform_info.h"

#if IS_BIG_ENDIAN
#define CMD_BBBB(a, b, c, d) (_SHIFTL(a, 24, 8) | _SHIFTL(b, 16, 8) | _SHIFTL(c, 8, 8) | _SHIFTL(d, 0, 8))
#define CMD_BBH(a, b, c)     (_SHIFTL(a, 24, 8) | _SHIFTL(b, 16, 8) | _SHIFTL(c, 0, 16))
#define CMD_HBB(a, b, c)     (_SHIFTL(a, 16, 16) | _SHIFTL(b, 8, 8) | _SHIFTL(c, 0, 8))
#define CMD_HH(a, b)         (_SHIFTL(a, 16, 16) | _SHIFTL(b, 0, 16))
#else
#define CMD_BBBB(a, b, c, d) (_SHIFTL(a, 0, 8) | _SHIFTL(b, 8, 8) | _SHIFTL(c, 16, 8) | _SHIFTL(d, 24, 8))
#define CMD_BBH(a, b, c)     (_SHIFTL(a, 0, 8) | _SHIFTL(b, 8, 8) | _SHIFTL(c, 16, 16))
#define CMD_HBB(a, b, c)     (_SHIFTL(a, 0, 16) | _SHIFTL(b, 16, 8) | _SHIFTL(c, 24, 8))
#define CMD_HH(a, b)         (_SHIFTL(a, 0, 16) | _SHIFTL(b, 16, 16))
#endif

#define CMD_W(a)   (a)
// uintptr_t (not u32): scene commands store segment/list POINTERS through this in static asset
// initializers. On the LP64 host a pointer truncated to a 32-bit u32 is not a compile-time constant
// (and loses its high bits); as uintptr_t it is a constant-foldable address constant. On the N64
// uintptr_t is 32-bit, so this is identical there. The receiving SCmd word members are uintptr_t to
// match (see include/scene.h).
#define CMD_PTR(a) (uintptr_t)(a)

#endif // COMMAND_MACROS_BASE_H
