#ifndef R64_INTERPOLATION_H
#define R64_INTERPOLATION_H

#include "gfx.h"
#include "../reality64/include/reality64/interpolation.h"

struct Actor;
struct GameState;
struct PlayState;
struct Room;
struct RoomContext;
struct View;
typedef struct R64InterpLink R64InterpLink;

enum {
    R64_EVENT_SCENE = 1,
    R64_EVENT_ROOM_SET = 2,
    R64_EVENT_CAMERA = 4,
    R64_EVENT_CAMERA_MODE = 8,
    R64_EVENT_CAMERA_SETTING = 16,
    R64_EVENT_CUTSCENE = 32,
    R64_EVENT_PAUSE = 64,
    R64_EVENT_FRAMEBUFFER = 128,
    R64_EVENT_GAME_STATE = 256
};

typedef struct {
    Gfx* lists[4];
} R64InterpMark;

extern s32 gR64InterpActive;

u64 R64Interp_ActorId(struct Actor* actor);
void R64Interp_ActorDeleted(struct Actor* actor);
R64InterpLink* R64Interp_LinkBegin(struct PlayState* play, void* actor, void** skeleton, s32 lod, Mtx* base,
                                 s32 count);
void R64Interp_LinkSlot(R64InterpLink* link, Mtx* matrix, Gfx* call, u32 limb, Gfx* mesh);
void R64Interp_LinkEnd(R64InterpLink* link);
void R64Interp_ResetPart(struct Actor* actor, u32 part);
void R64Interp_Billboard(Gfx* call, struct PlayState* play, struct Actor* actor, u32 category, u32 part,
                         u32 pass, u32 configuration, const float anchor[3], float scale, float spin, u32 provenance);
void R64Interp_Begin(struct GameState* state);
void R64Interp_End(const void* task);
void R64Interp_Root(Gfx* call, u32 pass);
void R64Interp_Play(struct PlayState* play);
void R64Interp_LatchCamera(struct PlayState* play);
void R64Interp_Camera(struct View* view, const Mtx* matrix, u32 role);
void R64Interp_Epoch(u64 event);
void R64Interp_Scene(void);
void R64Interp_RoomLoaded(struct RoomContext* roomCtx);
void R64Interp_Room(Gfx* call, struct PlayState* play, struct Room* room, u32 entry, u32 pass);
R64InterpMark R64Interp_Mark(GraphicsContext* gfxCtx);
void R64Interp_Collect(GraphicsContext* gfxCtx, R64InterpMark mark, u32 policy, u32 category);
void R64Interp_CollectWorld(GraphicsContext* gfxCtx, R64InterpMark mark, u32 category, u64 instance);

#define R64_INTERP_DRAW(gfxCtx, policy, category, ...) do { \
    R64InterpMark r64Mark; \
    if (gR64InterpActive) { \
        r64Mark = R64Interp_Mark(gfxCtx); \
    } \
    __VA_ARGS__; \
    if (gR64InterpActive) { \
        R64Interp_Collect(gfxCtx, r64Mark, policy, category); \
    } \
} while (0)

#define R64_INTERP_WORLD(gfxCtx, category, instance, ...) do { \
    u64 r64Instance = (instance); \
    R64InterpMark r64Mark; \
    if (gR64InterpActive) { \
        r64Mark = R64Interp_Mark(gfxCtx); \
    } \
    __VA_ARGS__; \
    if (gR64InterpActive) { \
        R64Interp_CollectWorld(gfxCtx, r64Mark, category, r64Instance); \
    } \
} while (0)

#endif
