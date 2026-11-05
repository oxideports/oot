#include <stdio.h>
#include <string.h>

#define _SHIFTL(v, s, w) ((unsigned)(((unsigned)(v) & ((0x01 << (w)) - 1)) << (s)))
#include "command_macros_base.h"

static int fails = 0;

static void chk(const char* n, unsigned got, const unsigned char exp[4]) {
    unsigned char b[4];

    memcpy(b, &got, 4);
    if (memcmp(b, exp, 4) != 0) {
        printf("FAIL %s: got %02x %02x %02x %02x want %02x %02x %02x %02x\n", n, b[0], b[1], b[2], b[3],
               exp[0], exp[1], exp[2], exp[3]);
        fails++;
    }
}

int main(void) {
    // On little-endian, the first packed field must occupy byte 0.
    chk("BBH", CMD_BBH(0x11, 0x22, 0x3344), (unsigned char[]){ 0x11, 0x22, 0x44, 0x33 });
    chk("BBBB", CMD_BBBB(0x11, 0x22, 0x33, 0x44), (unsigned char[]){ 0x11, 0x22, 0x33, 0x44 });
    chk("HBB", CMD_HBB(0x1122, 0x33, 0x44), (unsigned char[]){ 0x22, 0x11, 0x33, 0x44 });
    chk("HH", CMD_HH(0x1122, 0x3344), (unsigned char[]){ 0x22, 0x11, 0x44, 0x33 });
    chk("W", CMD_W(0x11223344), (unsigned char[]){ 0x44, 0x33, 0x22, 0x11 });
    // CS_START_SEQ word0 must place (seqId+1) in byte 1 (seqIdPlusOne), 0 in byte 0, startFrame in bytes 2-3.
    chk("STARTSEQ_w0", CMD_BBH(0, (0x22 + 1), 0x3344), (unsigned char[]){ 0x00, 0x23, 0x44, 0x33 });
    printf(fails ? "%d FAILED\n" : "OK\n", fails);
    return fails ? 1 : 0;
}
