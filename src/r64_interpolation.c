#include "r64_interpolation.h"
#include "game.h"
#include "array_count.h"
#include "play_state.h"
#include "player.h"
#include "regs.h"
#include "transition.h"
#include <stdlib.h>
#include <string.h>

_Static_assert(sizeof(R64TaskAnnotations) == 96, "native sidecar layout");
_Static_assert(sizeof(R64DrawAnnotation) == 96, "native draw layout");

s32 gR64InterpActive;

static R64DrawAnnotation sDraws[R64_INTERPOLATION_MAX_DRAWS];
static R64MatrixBinding sCamera[2];
static R64TaskAnnotations sTask = R64_TASK_ANNOTATIONS_INIT;
static u64 sSource, sEpoch = 1, sEvents, sScene, sRoomLoad;
static struct {
    void* segment;
    s16 num;
    u64 generation;
} sRoomLoads[2];
static u64 sRoomSet[2];
static GameStateFunc sGameMain;
static View* sWorldView;
static s32 sPaused, sActiveCam = -1, sPlaying, sDependent;
static u32 sHoldSerial;
static u64 sActorSerial, sGeneration;
typedef struct {
    void** skeleton;
    s32 lod, count;
    u64 parts[PLAYER_LIMB_MAX];
    Gfx* meshes[PLAYER_LIMB_MAX];
} R64LinkConfiguration;
typedef struct {
    struct Actor* actor;
    u64 serial;
    u64 linkGeneration;
    R64LinkConfiguration link;
    u64 parts[64];
    u32 configurations[64];
} R64ActorIdentity;
static R64ActorIdentity sActors[ACTOR_NUMBER_MAX + 1];
struct R64InterpLink {
    R64MatrixPalette palette;
    R64LinkConfiguration configuration;
    R64ActorIdentity* actor;
};
static R64InterpLink sLinks[4];
static u32 sLinkCount, sBillboardCount;
static R64BillboardRecipe sBillboards[R64_INTERPOLATION_MAX_DRAWS];

static u64 R64Interp_Generation(void) {
    if (++sGeneration == 0) {
        abort();
    }
    return sGeneration;
}

static R64ActorIdentity* R64Interp_Actor(struct Actor* actor) {
    u32 i, freeSlot = ARRAY_COUNT(sActors);
    for (i = 0; i < ARRAY_COUNT(sActors); i++) {
        if (sActors[i].actor == actor) {
            return &sActors[i];
        }
        if (sActors[i].actor == NULL) {
            freeSlot = i;
        }
    }
    if (freeSlot == ARRAY_COUNT(sActors) || ++sActorSerial == 0) {
        abort();
    }
    memset(&sActors[freeSlot], 0, sizeof(sActors[freeSlot]));
    sActors[freeSlot].actor = actor;
    sActors[freeSlot].serial = sActorSerial;
    return &sActors[freeSlot];
}

u64 R64Interp_ActorId(struct Actor* actor) {
    return R64Interp_Actor(actor)->serial;
}

void R64Interp_ActorDeleted(struct Actor* actor) {
    u32 i;
    for (i = 0; i < ARRAY_COUNT(sActors); i++) {
        if (sActors[i].actor == actor) {
            sActors[i].actor = NULL;
            return;
        }
    }
}

void R64Interp_Epoch(u64 event) {
    if (++sEpoch == 0) {
        abort();
    }
    sEvents |= event;
}

void R64Interp_Scene(void) {
    if (++sScene > UINT32_MAX) {
        abort();
    }
    memset(sRoomLoads, 0, sizeof(sRoomLoads));
    sRoomLoad = 0;
    R64Interp_Epoch(R64_EVENT_SCENE);
}

static u64 R64Interp_RoomGeneration(Room* room) {
    u32 i;
    if (room->segment == NULL) {
        return 0;
    }
    for (i = 0; i < 2; i++) {
        if (sRoomLoads[i].segment == room->segment && sRoomLoads[i].num == room->num) {
            return sRoomLoads[i].generation;
        }
    }
    abort();
}

void R64Interp_RoomLoaded(RoomContext* roomCtx) {
    u32 slot = 0;
    if (++sRoomLoad > UINT32_MAX) {
        abort();
    }
    if (roomCtx->prevRoom.segment != NULL && sRoomLoads[0].segment == roomCtx->prevRoom.segment &&
        sRoomLoads[0].num == roomCtx->prevRoom.num) {
        slot = 1;
    }
    sRoomLoads[slot].segment = roomCtx->curRoom.segment;
    sRoomLoads[slot].num = roomCtx->curRoom.num;
    sRoomLoads[slot].generation = (sScene << 32) | sRoomLoad;
}

void R64Interp_Begin(GameState* state) {
    gR64InterpActive = R64InterpolationActive();
    if (++sSource == 0) {
        abort();
    }
    if (sGameMain != state->main) {
        sGameMain = state->main;
        R64Interp_Epoch(R64_EVENT_GAME_STATE);
    }
    if (!gR64InterpActive) {
        return;
    }
    sTask.source = sSource;
    sTask.producer_sample = osGetTime();
    sTask.draw_count = 0;
    sTask.flags = 0;
    sTask.events = 0;
    sTask.draws = sDraws;
    sWorldView = NULL;
    sPlaying = false;
    sHoldSerial = 0;
    sLinkCount = 0;
    sBillboardCount = 0;
    memset(sCamera, 0, sizeof(sCamera));
}

void R64Interp_Play(PlayState* play) {
    u64 rooms[2];
    s32 paused = IS_PAUSED(&play->pauseCtx);
    s32 dependent;
    sPlaying = true;
    sWorldView = &play->view;
    if (paused != sPaused) {
        sPaused = paused;
        R64Interp_Epoch(R64_EVENT_PAUSE);
    }
    rooms[0] = R64Interp_RoomGeneration(&play->roomCtx.curRoom);
    rooms[1] = R64Interp_RoomGeneration(&play->roomCtx.prevRoom);
    if (rooms[0] > rooms[1]) {
        u64 swap = rooms[0];
        rooms[0] = rooms[1];
        rooms[1] = swap;
    }
    if (rooms[0] != sRoomSet[0] || rooms[1] != sRoomSet[1]) {
        memcpy(sRoomSet, rooms, sizeof(rooms));
        R64Interp_Epoch(R64_EVENT_ROOM_SET);
    }
    dependent = paused || R_PAUSE_BG_PRERENDER_STATE != PAUSE_BG_PRERENDER_OFF ||
                gTransitionTileState != TRANS_TILE_OFF || gVisMonoColor.a != 0;
    if (gR64InterpActive && dependent) {
        sTask.flags |= R64_INTERPOLATION_FRAMEBUFFER_DEPENDENT;
    }
    if (dependent || dependent != sDependent) {
        R64Interp_Epoch(R64_EVENT_FRAMEBUFFER);
    }
    sDependent = dependent;
}

void R64Interp_LatchCamera(PlayState* play) {
    if (sActiveCam != play->activeCamId) {
        sActiveCam = play->activeCamId;
        R64Interp_Epoch(R64_EVENT_CAMERA);
    }
    if (!gR64InterpActive) {
        return;
    }
    sTask.epoch = sEpoch;
    sTask.events = sEvents;
    sEvents = 0;
}

void R64Interp_Camera(View* view, const Mtx* matrix, u32 role) {
    if (gR64InterpActive && view == sWorldView) {
        sCamera[role].operand = (uintptr_t)matrix;
        sCamera[role].role = role;
    }
}

static R64DrawAnnotation* R64Interp_Add(Gfx* call, u32 policy, u32 category, u32 pass) {
    R64DrawAnnotation* draw;
    size_t i;
    if (!gR64InterpActive) {
        return NULL;
    }
    for (i = 0; i < sTask.draw_count; i++) {
        if (sDraws[i].scope.address == (uintptr_t)call) {
            return NULL;
        }
    }
    if (sTask.draw_count == R64_INTERPOLATION_MAX_DRAWS) {
        abort();
    }
    draw = &sDraws[sTask.draw_count++];
    memset(draw, 0, sizeof(*draw));
    draw->scope.address = (uintptr_t)call;
    draw->policy = policy;
    draw->identity.namespace_id = category;
    draw->identity.generation = sSource;
    draw->identity.part = ++sHoldSerial;
    draw->identity.pass = pass;
    if (policy != R64_TRANSFORM_SCREEN_SPACE && sWorldView != NULL) {
        draw->matrices = sCamera;
        draw->matrix_count = 2;
    }
    return draw;
}

R64InterpLink* R64Interp_LinkBegin(PlayState* play, void* actor, void** skeleton, s32 lod, Mtx* base, s32 count) {
    R64InterpLink* link;
    if (!gR64InterpActive || sWorldView != &play->view || sPaused || actor != GET_PLAYER(play) ||
        ((Actor*)actor)->scale.y <= 0.0f) {
        return NULL;
    }
    if (sLinkCount == ARRAY_COUNT(sLinks) || count < 0 || count > PLAYER_LIMB_MAX) {
        abort();
    }
    link = &sLinks[sLinkCount++];
    memset(link, 0, sizeof(*link));
    link->actor = R64Interp_Actor(actor);
    link->configuration.skeleton = skeleton;
    link->configuration.lod = lod;
    link->configuration.count = count;
    link->palette.base = (uintptr_t)base;
    link->palette.parts = link->configuration.parts;
    link->palette.count = count;
    return link;
}

void R64Interp_LinkSlot(R64InterpLink* link, Mtx* matrix, Gfx* call, u32 limb, Gfx* mesh) {
    size_t slot;
    R64DrawAnnotation* draw;
    if (link == NULL) {
        return;
    }
    slot = matrix - (Mtx*)link->palette.base;
    if (slot >= link->palette.count || limb >= PLAYER_LIMB_MAX) {
        abort();
    }
    link->configuration.parts[slot] = limb;
    link->configuration.meshes[slot] = mesh;
    if (call != NULL) {
        draw = R64Interp_Add(call, R64_TRANSFORM_INTERPOLATE, 3, 0);
        if (draw == NULL) {
            abort();
        }
        draw->identity.instance = link->actor - sActors;
        draw->identity.part = limb;
        draw->palette = &link->palette;
    }
}

void R64Interp_LinkEnd(R64InterpLink* link) {
    size_t i;
    s32 changed;
    if (link == NULL) {
        return;
    }
    changed = link->actor->linkGeneration == 0 || link->actor->link.skeleton != link->configuration.skeleton ||
              link->actor->link.lod != link->configuration.lod || link->actor->link.count != link->configuration.count;
    for (i = 0; i < PLAYER_LIMB_MAX; i++) {
        changed |= link->actor->link.parts[i] != link->configuration.parts[i] ||
                   link->actor->link.meshes[i] != link->configuration.meshes[i];
    }
    if (changed) {
        link->actor->link = link->configuration;
        link->actor->linkGeneration = R64Interp_Generation();
    }
    for (i = 0; i < sTask.draw_count; i++) {
        if (sDraws[i].palette == &link->palette) {
            sDraws[i].identity.generation = link->actor->linkGeneration;
        }
    }
}

void R64Interp_ResetPart(struct Actor* actor, u32 part) {
    if (part >= 64) {
        abort();
    }
    R64Interp_Actor(actor)->parts[part] = R64Interp_Generation();
}

void R64Interp_Billboard(Gfx* call, PlayState* play, struct Actor* actor, u32 category, u32 part,
                         u32 pass, u32 configuration, const float anchor[3], float scale, float spin, u32 provenance) {
    R64DrawAnnotation* draw;
    R64BillboardRecipe* recipe;
    u32 row, col;
    if (!gR64InterpActive || sWorldView != &play->view || sPaused) {
        return;
    }
    draw = R64Interp_Add(call, R64_TRANSFORM_BILLBOARD_HOLD, category, pass);
    if (draw == NULL || sBillboardCount == ARRAY_COUNT(sBillboards)) {
        abort();
    }
    recipe = &sBillboards[sBillboardCount++];
    memcpy(recipe->anchor, anchor, sizeof(recipe->anchor));
    for (row = 0; row < 3; row++) {
        recipe->scale[row] = scale;
        for (col = 0; col < 3; col++) {
            recipe->basis[row][col] = play->billboardMtxF.mf[row][col];
        }
    }
    recipe->spin = spin;
    recipe->provenance = provenance;
    draw->billboard = recipe;
    draw->identity.part = part;
    draw->identity.subdraw = 1;
    draw->identity.generation = sScene;
    if (actor != NULL) {
        R64ActorIdentity* identity = R64Interp_Actor(actor);
        if (part >= ARRAY_COUNT(identity->parts)) {
            abort();
        }
        if (identity->parts[part] == 0 || identity->configurations[part] != configuration) {
            identity->parts[part] = R64Interp_Generation();
            identity->configurations[part] = configuration;
        }
        draw->identity.instance = identity - sActors;
        draw->identity.generation = identity->parts[part];
    }
}

void R64Interp_Root(Gfx* call, u32 pass) {
    R64DrawAnnotation* draw = R64Interp_Add(
        call, (!sPlaying || sPaused || pass == 2) ? R64_TRANSFORM_SCREEN_SPACE : R64_TRANSFORM_HOLD_MODEL, 12, pass);
    if (draw != NULL) {
        draw->identity.generation = sScene;
        draw->identity.part = 0;
    }
}

void R64Interp_Room(Gfx* call, PlayState* play, Room* room, u32 entry, u32 pass) {
    R64DrawAnnotation* draw = R64Interp_Add(call, R64_TRANSFORM_STATIC_WORLD, 1, pass);
    if (draw != NULL) {
        draw->identity.instance = ((u64)(u16)play->sceneId << 16) | (u16)room->num;
        draw->identity.generation = R64Interp_RoomGeneration(room);
        draw->identity.part = entry;
    }
}

R64InterpMark R64Interp_Mark(GraphicsContext* gfxCtx) {
    R64InterpMark mark = { 0 };
    if (gR64InterpActive) {
        mark = (R64InterpMark){ { gfxCtx->polyOpa.p, gfxCtx->polyXlu.p, gfxCtx->overlay.p, gfxCtx->work.p } };
    }
    return mark;
}

void R64Interp_Collect(GraphicsContext* gfxCtx, R64InterpMark mark, u32 policy, u32 category) {
    R64InterpMark end;
    u32 pass;
    if (!gR64InterpActive) {
        return;
    }
    end = R64Interp_Mark(gfxCtx);
    for (pass = 0; pass < 4; pass++) {
        Gfx* p;
        for (p = mark.lists[pass]; p < end.lists[pass]; p++) {
            if ((p->words.w0 >> 24) == G_DL) {
                if (((p->words.w0 >> 16) & 0xFF) == G_DL_PUSH) {
                    R64Interp_Add(p, policy, category, pass);
                } else {
                    uintptr_t target = p->words.w1;
                    if (target > (uintptr_t)p && target <= (uintptr_t)end.lists[pass]) {
                        p = (Gfx*)target - 1;
                    }
                }
            }
        }
    }
}

void R64Interp_CollectWorld(GraphicsContext* gfxCtx, R64InterpMark mark, u32 category, u64 instance) {
    uintptr_t first = sTask.draw_count, i;
    u32 parts[4] = { 0 };
    if (!gR64InterpActive) {
        return;
    }
    R64Interp_Collect(gfxCtx, mark, R64_TRANSFORM_HOLD_MODEL, category);
    for (i = first; i < sTask.draw_count; i++) {
        R64DrawAnnotation* draw = &sDraws[i];
        draw->identity.instance = instance;
        draw->identity.generation = sScene;
        draw->identity.part = parts[draw->identity.pass]++;
    }
}

void R64Interp_End(const void* task) {
    if (!gR64InterpActive) {
        return;
    }
    if (!sPlaying) {
        sTask.epoch = sEpoch;
        sTask.events = sEvents;
        sEvents = 0;
    }
    if (R64InterpolationAttach(task, &sTask) != 0) {
        abort();
    }
}
