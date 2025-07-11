from __future__ import annotations

from minigrid.core.constants import COLOR_NAMES
from minigrid.core.grid import Grid
from minigrid.core.mission import MissionSpace
from minigrid.core.world_object import Door, Goal, Wall
from minigrid.minigrid_env import MiniGridEnv

#from minigrid.core.world_object_multiroom import GoalSoundEngine
from minigrid.core.world_object_multiroom import ProximityDoorSoundEngine
from minigrid.core.world_object_multiroom import ProximityColorDoorSoundEngine
from gymnasium import spaces
import numpy as np
from os import path


class MultiRoom:
    def __init__(self, top, size, entryDoorPos, exitDoorPos):
        self.top = top
        self.size = size
        self.entryDoorPos = entryDoorPos
        self.exitDoorPos = exitDoorPos


class MultiRoomEnvSound(MiniGridEnv):
    """
    ## Description

    This environment has a series of connected rooms with doors that must be
    opened in order to get to the next room. The final room has the green goal
    square the agent must get to. This environment is extremely difficult to
    solve using RL alone. However, by gradually increasing the number of rooms
    and building a curriculum, the environment can be solved.

    ## Mission Space

    "traverse the rooms to get to the goal"

    ## Action Space

    | Num | Name         | Action                    |
    |-----|--------------|---------------------------|
    | 0   | left         | Turn left                 |
    | 1   | right        | Turn right                |
    | 2   | forward      | Move forward              |
    | 3   | pickup       | Unused                    |
    | 4   | drop         | Unused                    |
    | 5   | toggle       | Toggle/activate an object |
    | 6   | done         | Unused                    |

    ## Observation Encoding

    - Each tile is encoded as a 3 dimensional tuple:
        `(OBJECT_IDX, COLOR_IDX, STATE)`
    - `OBJECT_TO_IDX` and `COLOR_TO_IDX` mapping can be found in
        [minigrid/core/constants.py](minigrid/core/constants.py)
    - `STATE` refers to the door state with 0=open, 1=closed and 2=locked

    ## Rewards

    A reward of '1 - 0.9 * (step_count / max_steps)' is given for success, and '0' for failure.

    ## Termination

    The episode ends if any one of the following conditions is met:

    1. The agent reaches the goal.
    2. Timeout (see `max_steps`).

    ## Registered Configurations

    S: size of map SxS.
    N: number of rooms.

    - `MiniGrid-MultiRoom-N2-S4-v0` (two small rooms)
    - `MiniGrid-MultiRoom-N4-S5-v0` (four rooms)
    - `MiniGrid-MultiRoom-N6-v0` (six rooms)

    """

    def __init__(
        self,
        minNumRooms,
        maxNumRooms,
        maxRoomSize=10,
        max_steps: int | None = None,
        **kwargs,
    ):
        assert minNumRooms > 0
        assert maxNumRooms >= minNumRooms
        assert maxRoomSize >= 4

        self.minNumRooms = minNumRooms
        self.maxNumRooms = maxNumRooms
        self.maxRoomSize = maxRoomSize

        self.rooms = []

        mission_space = MissionSpace(mission_func=self._gen_mission)

        self.size = 25
        """self.size = kwargs.pop("width", 25)
        height = kwargs.pop("height", self.size)
        sound_engine = kwargs.pop("sound_engine", None)"""

        if max_steps is None:
            max_steps = maxNumRooms * 20

        super().__init__(
            mission_space=mission_space,
            width=self.size,
            height=self.size,
            max_steps=max_steps,
            **kwargs,
        )

        # Ajout du son
        self.sound_engine = ProximityDoorSoundEngine() 
        #self.sound_engine = ProximityColorDoorSoundEngine()
        self.sound_space = spaces.Box(
            low=-1.0,
            high=1.0,
            shape=(600,),
            dtype=np.float32
        )

        old_observation_space = self.observation_space
        new_obs_dict = {key: value for key, value in old_observation_space.items()}
        new_obs_dict["sound"] = self.sound_space
        self.observation_space = spaces.Dict(new_obs_dict)


    @staticmethod
    def _gen_mission():
        return "traverse the rooms to get to the goal"

    def _gen_grid(self, width, height):
        roomList = []

        # Choose a random number of rooms to generate
        numRooms = self._rand_int(self.minNumRooms, self.maxNumRooms + 1)

        while len(roomList) < numRooms:
            curRoomList = []

            entryDoorPos = (self._rand_int(0, width - 2), self._rand_int(0, width - 2))

            # Recursively place the rooms
            self._placeRoom(
                numRooms,
                roomList=curRoomList,
                minSz=4,
                maxSz=self.maxRoomSize,
                entryDoorWall=2,
                entryDoorPos=entryDoorPos,
            )

            if len(curRoomList) > len(roomList):
                roomList = curRoomList

        # Store the list of rooms in this environment
        assert len(roomList) > 0
        self.rooms = roomList

        # Create the grid
        self.grid = Grid(width, height)
        wall = Wall()

        prevDoorColor = None

        # For each room
        for idx, room in enumerate(roomList):
            topX, topY = room.top
            sizeX, sizeY = room.size

            # Draw the top and bottom walls
            for i in range(0, sizeX):
                self.grid.set(topX + i, topY, wall)
                self.grid.set(topX + i, topY + sizeY - 1, wall)

            # Draw the left and right walls
            for j in range(0, sizeY):
                self.grid.set(topX, topY + j, wall)
                self.grid.set(topX + sizeX - 1, topY + j, wall)

            # If this isn't the first room, place the entry door
            if idx > 0:
                # Pick a door color different from the previous one
                doorColors = set(COLOR_NAMES)
                if prevDoorColor:
                    doorColors.remove(prevDoorColor)
                # Note: the use of sorting here guarantees determinism,
                # This is needed because Python's set is not deterministic
                doorColor = self._rand_elem(sorted(doorColors))

                entryDoor = Door(doorColor)
                self.grid.set(room.entryDoorPos[0], room.entryDoorPos[1], entryDoor)
                prevDoorColor = doorColor

                prevRoom = roomList[idx - 1]
                prevRoom.exitDoorPos = room.entryDoorPos

        # Randomize the starting agent position and direction
        self.place_agent(roomList[0].top, roomList[0].size)

        # Place the final goal in the last room
        self.goal_pos = self.place_obj(Goal(), roomList[-1].top, roomList[-1].size)

        self.mission = "traverse the rooms to get to the goal"

    def _placeRoom(self, numLeft, roomList, minSz, maxSz, entryDoorWall, entryDoorPos):
        # Choose the room size randomly
        sizeX = self._rand_int(minSz, maxSz + 1)
        sizeY = self._rand_int(minSz, maxSz + 1)

        # The first room will be at the door position
        if len(roomList) == 0:
            topX, topY = entryDoorPos
        # Entry on the right
        elif entryDoorWall == 0:
            topX = entryDoorPos[0] - sizeX + 1
            y = entryDoorPos[1]
            topY = self._rand_int(y - sizeY + 2, y)
        # Entry wall on the south
        elif entryDoorWall == 1:
            x = entryDoorPos[0]
            topX = self._rand_int(x - sizeX + 2, x)
            topY = entryDoorPos[1] - sizeY + 1
        # Entry wall on the left
        elif entryDoorWall == 2:
            topX = entryDoorPos[0]
            y = entryDoorPos[1]
            topY = self._rand_int(y - sizeY + 2, y)
        # Entry wall on the top
        elif entryDoorWall == 3:
            x = entryDoorPos[0]
            topX = self._rand_int(x - sizeX + 2, x)
            topY = entryDoorPos[1]
        else:
            assert False, entryDoorWall

        # If the room is out of the grid, can't place a room here
        if topX < 0 or topY < 0:
            return False
        if topX + sizeX > self.width or topY + sizeY >= self.height:
            return False

        # If the room intersects with previous rooms, can't place it here
        for room in roomList[:-1]:
            nonOverlap = (
                topX + sizeX < room.top[0]
                or room.top[0] + room.size[0] <= topX
                or topY + sizeY < room.top[1]
                or room.top[1] + room.size[1] <= topY
            )

            if not nonOverlap:
                return False

        # Add this room to the list
        roomList.append(MultiRoom((topX, topY), (sizeX, sizeY), entryDoorPos, None))

        # If this was the last room, stop
        if numLeft == 1:
            return True

        # Try placing the next room
        for i in range(0, 8):
            # Pick which wall to place the out door on
            wallSet = {0, 1, 2, 3}
            wallSet.remove(entryDoorWall)
            exitDoorWall = self._rand_elem(sorted(wallSet))
            nextEntryWall = (exitDoorWall + 2) % 4

            # Pick the exit door position
            # Exit on right wall
            if exitDoorWall == 0:
                exitDoorPos = (topX + sizeX - 1, topY + self._rand_int(1, sizeY - 1))
            # Exit on south wall
            elif exitDoorWall == 1:
                exitDoorPos = (topX + self._rand_int(1, sizeX - 1), topY + sizeY - 1)
            # Exit on left wall
            elif exitDoorWall == 2:
                exitDoorPos = (topX, topY + self._rand_int(1, sizeY - 1))
            # Exit on north wall
            elif exitDoorWall == 3:
                exitDoorPos = (topX + self._rand_int(1, sizeX - 1), topY)
            else:
                assert False

            # Recursively create the other rooms
            success = self._placeRoom(
                numLeft - 1,
                roomList=roomList,
                minSz=minSz,
                maxSz=maxSz,
                entryDoorWall=nextEntryWall,
                entryDoorPos=exitDoorPos,
            )

            if success:
                break

        return True
    
    """def gen_obs(self):
        obs = super().gen_obs()
        obs["sound"] = np.asarray(self.sound_engine.play(self), dtype=np.float32)

        assert self.observation_space["image"].contains(obs["image"]), f"Image observation is invalid: {obs['image']}"
        assert self.observation_space["direction"].contains(obs["direction"]), f"Direction observation is invalid: {obs['direction']}"
        if "mission" in self.observation_space.spaces:
            assert self.observation_space["mission"].contains(obs["mission"]), f"Mission observation is invalid: {obs['mission']}"
        assert self.observation_space["sound"].contains(obs["sound"]), f"Sound observation is invalid: {obs['sound']}"

        assert self.observation_space.contains(obs), "Observation is outside the defined observation space!"
        return obs"""
    def gen_obs(self):
        obs = super().gen_obs()
        obs["sound"] = self.sound_engine.play(self)
        return {
            "sound": obs["sound"],
            "image": obs["image"],
            "direction": obs["direction"],
            "mission": obs["mission"] if "mission" in obs else None
        }


if __name__ == "__main__":

    """env = MultiRoomEnvSound(
        minNumRooms=2,
        maxNumRooms=4,
        maxRoomSize=5,
        #width=25,
        #height=25,
        #sound_engine=ProximityDoorSoundEngine(),
    )

    #a = env.reset()

    obs, info = env.reset()

    # Affichage initial
    print(obs)
    print()
    print(env.observation_space)
    print("Son :", np.all(obs["sound"] == 0))
    print("Image", np.all(obs["image"] == 0))"""

    env = MultiRoomEnvSound(
        minNumRooms=1,
        maxNumRooms=3,
        maxRoomSize=4,
        render_mode="human"  # mode d'affichage human
    )

    obs, info = env.reset()
    total_reward = 0
    terminated = False
    truncated = False
    nb_sons = 0

    print(obs)
    print()
    print(env.observation_space)
    print("Son :", np.all(obs["sound"] == 0))
    print("Image", np.all(obs["image"] == 0))

    while not (terminated or truncated):
        env.render()  # Affichage de l'état courant de l'environnement
        action = env.action_space.sample()  # Choix aléatoire d'une action
        obs, reward, terminated, truncated, info = env.step(action)
        total_reward += reward
        if np.any(obs["sound"] != 0):
            nb_sons += 1
            son_detecte = np.where(obs["sound"] != 0)[0]
            #print("Son détecté:", son_detecte)
            print("Son détecté:", obs["sound"])
        #print("Son :", np.all(obs["sound"] == 0))
        #print("Image", np.all(obs["image"] == 0))

    print("Episode terminé avec un reward total de:", total_reward)
    print("Nombre de sons détectés :", nb_sons)
    input("Appuyez sur Entrée pour quitter...")
    env.close()
    pass
    