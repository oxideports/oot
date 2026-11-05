#ifndef SEGMENTED_ADDRESS_H
#define SEGMENTED_ADDRESS_H

#include "ultra64.h"
#include "stdint.h"

extern uintptr_t gSegments[NUM_SEGMENTS];

// A segment address is (segNum << 24) | offset, so it always fits below 0x10000000. On real N64 the
// relocated result is a K0 address (>= 0x80000000) whose RDRAM offset fits in the low 24 bits, so
// re-relocating one is a no-op (SEGMENT_NUMBER picks gSegments[0]==0 and K0BASE is re-added). reality64
// runs on 64-bit native pointers that do NOT round-trip through this u32-truncating macro, so a second
// relocation of an already-virtual pointer would corrupt it. The game legitimately relocates shared
// collision headers (CollisionHeader_SegmentedToVirtual) once per actor that references them, relying
// on that N64 idempotency — so replicate it: pass through anything that is already a virtual pointer
// (>= 0x10000000). NULL and genuine segment addresses (< 0x10000000) still relocate as before, which
// keeps the SEGMENTED_TO_VIRTUAL(NULL) sentinel intact.
#define SEGMENTED_TO_VIRTUAL(addr)                                                                     \
    ((void*)((uintptr_t)(addr) >= 0x10000000u ? (uintptr_t)(addr)                                      \
                                              : gSegments[SEGMENT_NUMBER(addr)] + SEGMENT_OFFSET(addr) + \
                                                    K0BASE))

#endif
