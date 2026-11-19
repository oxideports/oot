/*
 * Native no-audio bootstrap.
 *
 * The audio-data pipeline (Audiobank/Audioseq/Audiotable blobs + the per-sequence _Sequence_* symbols)
 * is a later milestone; real playback runs through reality64's audio adapter (arie) then. Until that lands,
 * the four audio-table TUs are excluded from the native build and this file provides the symbols they
 * would define, as empty tables. The engine reads numEntries == 0 and preloads nothing; the audio thread
 * still initializes (in NO_RSP mode) so the boot handshake (AudioMgr_WaitForInit) completes.
 *
 * Compiled only in the native/reality64 CMake build (the decomp Makefile builds the real tables from the
 * audio XML instead), so no gate is needed here.
 */
#include "alignment.h"
#include "buffers.h"
#include "audio.h"

// Empty asset tables: header.numEntries == 0, no entries. Replaces sequence_table.c / soundfont_table.c /
// samplebank_table.c, which also carry the _Sequence_* and __Audio*SegmentRom* data references.
AudioTable gSequenceTable = { 0 };
AudioTable gSoundFontTable = { 0 };
AudioTable gSampleBankTable = { 0 };

// seq -> soundfont map; empty (no sequences to map).
u8 gSequenceFontTable[1] = { 0 };

// From session_init.c. Tempo is data-independent; the pool sizes only need the heap to partition cleanly
// since nothing permanent is preloaded.
TempoData gTempoData = {
    0x1C00,            // unk_00
    SEQTICKS_PER_BEAT, // seqTicksPerBeat
};

// With empty tables nothing is permanently loaded, so keep the init + permanent pools small and leave
// the bulk of gAudioHeap as the session pool — the note buffer (numNotes * sizeof(Note), from the audio
// spec) is carved from there, and starving it leaves gAudioCtx.notes NULL (AudioHeap_Init crash).
AudioHeapInitSizes gAudioHeapInitSizes = {
    ALIGN16(sizeof(gAudioHeap) - 0x100), // heap size
    ALIGN16(0x4000),                     // init pool size (AI buffers + soundfont list)
    ALIGN16(0x1000),                     // permanent pool size
};
