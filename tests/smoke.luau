-- Смоук-тест без Roblox Studio: собирает место через Rojo и запускает серверные модули
-- в Lune (Luau-рантайм с Roblox API). Проверяет генерацию лабиринта, постройку карт
-- (неверное имя свойства или Enum сразу даст ошибку), ИИ монстра и Тени.
--
-- Запуск:
--   rojo build default.project.json -o test.rbxlx
--   lune run tests/smoke test.rbxlx
--
-- Методы движка, которых нет в Lune (терраин, твины, физика), заменены заглушками.
local fs = require("@lune/fs")
local luau = require("@lune/luau")
local roblox = require("@lune/roblox")
local process = require("@lune/process")

local placePath = process.args[#process.args]
local game = roblox.deserializePlace(fs.readFile(placePath))
local Workspace = game:GetService("Workspace")
local terrain = roblox.Instance.new("Terrain")
terrain.Parent = Workspace

-- Engine methods Lune doesn't implement.
local terrainCalls = {}
roblox.implementMethod("Terrain", "FillBlock", function(_, cf, size, material)
	assert(typeof(cf) == "CFrame" and typeof(size) == "Vector3" and typeof(material) == "EnumItem", "FillBlock args")
	table.insert(terrainCalls, material.Name)
end)
roblox.implementMethod("Terrain", "SetMaterialColor", function(_, material, color)
	assert(typeof(material) == "EnumItem" and typeof(color) == "Color3")
end)
roblox.implementMethod("InsertService", "LoadAsset", function(_, id)
	local model = roblox.Instance.new("Model")
	local decal = roblox.Instance.new("Decal")
	decal.Texture = "rbxassetid://" .. (id + 1)
	decal.Parent = model
	return model
end)
local tweens = 0
roblox.implementMethod("TweenService", "Create", function(_, instance, info, goals)
	assert(typeof(info) == "TweenInfo" or type(info) == "table")
	for key, value in goals do
		instance[key] = instance[key] -- property must exist
	end
	tweens += 1
	return { Play = function() end }
end)
roblox.implementMethod("DataStoreService", "GetDataStore", function()
	error("no API access in test")
end)
roblox.implementMethod("RunService", "IsStudio", function()
	return true
end)
roblox.implementMethod("Part", "SetNetworkOwner", function() end)
local fakePlayers = {}
roblox.implementMethod("Players", "GetPlayers", function()
	return fakePlayers
end)
local fired = {}
roblox.implementMethod("RemoteEvent", "FireClient", function(self, player, ...)
	table.insert(fired, { self.Name, player.Name, ... })
end)
roblox.implementMethod("Workspace", "Raycast", function()
	return nil
end)
local moves = 0
roblox.implementMethod("Humanoid", "MoveTo", function(_, position)
	assert(typeof(position) == "Vector3")
	moves += 1
end)
roblox.implementMethod("Humanoid", "SetStateEnabled", function(_, state, enabled)
	assert(state.EnumType == roblox.Enum.HumanoidStateType and type(enabled) == "boolean")
end)
roblox.implementMethod("Model", "PivotTo", function(self, cf)
	local offset = cf * self.PrimaryPart.CFrame:Inverse()
	for _, d in self:GetDescendants() do
		if d:IsA("BasePart") then
			d.CFrame = offset * d.CFrame
			d.Position = d.CFrame.Position
		end
	end
end)

-- В Lune Position хранится отдельно от CFrame — синхронизируем вручную.
local function syncPositions(root)
	for _, d in root:GetDescendants() do
		if d:IsA("BasePart") then
			d.Position = d.CFrame.Position
		end
	end
end

-- Minimal Random / RaycastParams / TweenInfo / task polyfills.
local Random = {}
Random.__index = Random
function Random.new(seed)
	local state = seed or 12345
	return setmetatable({ state = state }, Random)
end
function Random:NextNumber(min, max)
	self.state = (self.state * 1103515245 + 12345) % 2147483648
	local t = self.state / 2147483648
	if min then
		return min + (max - min) * t
	end
	return t
end
function Random:NextInteger(min, max)
	return math.min(max, min + math.floor(self:NextNumber() * (max - min + 1)))
end
local RaycastParams = {
	new = function()
		return {}
	end,
}
local TweenInfo = {
	new = function(...)
		return { ... }
	end,
}

local loaded = {}
local function makeEnv(scriptInstance)
	local env = {}
	env.game = game
	env.workspace = Workspace
	env.script = scriptInstance
	env.Random = Random
	env.RaycastParams = RaycastParams
	env.TweenInfo = TweenInfo
	env.warn = function(...)
		print("[warn]", ...)
	end
	env.task = { spawn = function() end, delay = function() end, wait = function() end }
	for name, value in roblox do
		if type(name) == "string" and name:match("^%u") then
			env[name] = value
		end
	end
	-- Lune stores Position separately from CFrame; give parts a readable default.
	env.Instance = {
		new = function(className)
			local instance = roblox.Instance.new(className)
			if instance:IsA("BasePart") then
				instance.Position = roblox.Vector3.zero
			end
			return instance
		end,
	}
	env.require = function(module)
		assert(typeof(module) == "Instance" and module.ClassName == "ModuleScript", "require expects a ModuleScript")
		if loaded[module] == nil then
			local fn = luau.load(module.Source, { debugName = module:GetFullName(), environment = makeEnv(module) })
			loaded[module] = fn()
		end
		return loaded[module]
	end
	return env
end

local ReplicatedStorage = game:GetService("ReplicatedStorage")
local server = game:GetService("ServerScriptService").Server
local function req(name)
	return makeEnv(server).require(server[name])
end

local Config = makeEnv(server).require(ReplicatedStorage.Shared.Config)
Config.Textures.Bark = 100
Config.Textures.MazeWall = 200
Config.Textures.Poster = 300
Config.Textures.Scratches = 400
Config.Textures.Blood = 500
Config.Textures.Fence = 600

local Textures = req("Textures")
Textures.preload()
assert(Textures.get("Bark") == "rbxassetid://101", Textures.get("Bark"))
assert(Textures.get("MazeFloor") == nil)

local MapBuilder = req("MapBuilder")
local ForestBuilder = req("ForestBuilder")
local Monster = req("Monster")
local Shadow = req("Shadow")
req("Scare")
req("GameLoop")
req("PlayerData")

-- Лабиринт: все клетки достижимы, пути идут только через проходы и кратчайшие.
local Maze = req("Maze")
for seed = 1, 200 do
	local rng = Random.new(seed)
	local width, height = rng:NextInteger(2, 14), rng:NextInteger(2, 14)
	local maze = Maze.generate(width, height, rng, (seed % 3) * 0.1)
	local count = width * height
	for i = 1, count do
		for j in maze.links[i] do
			assert(maze.links[j][i], "asymmetric link")
			assert(table.find(maze:gridNeighbors(i), j), "link to a non-neighbour")
		end
	end
	local distances = maze:distances(1)
	for i = 1, count do
		assert(distances[i] ~= nil, "unreachable cell " .. i)
	end
	for _ = 1, 10 do
		local a, b = rng:NextInteger(1, count), rng:NextInteger(1, count)
		local path = maze:path(a, b)
		assert(path and path[1] == a and path[#path] == b, "bad path endpoints")
		for k = 2, #path do
			assert(maze:isLinked(path[k - 1], path[k]), "path goes through a wall")
		end
		if a == 1 then
			assert(#path - 1 == distances[b], "path is not the shortest")
		end
	end
	for _, cell in maze:deadEnds() do
		assert(#maze:exits(cell) == 1)
	end
end
print("maze ok")

local lobby = MapBuilder.buildLobby()
assert(lobby.spawn:IsA("SpawnLocation"))

for seed = 1, 5 do
	local rng = Random.new(seed)
	local layout = MapBuilder.buildMaze(rng)
	assert(#layout.keys == Config.KeysToEscape, "keys " .. #layout.keys)
	local forest = ForestBuilder.build(rng, layout.forestEntry)
	forest:powerOn()
	assert(forest.gateLabel.Text == "ВЫЕЗД ОТКРЫТ")

	local monster = Monster.new(layout)
	syncPositions(monster.model)
	for _ = 1, 50 do
		monster:step()
	end
	assert(monster.model.PrimaryPart.Name == "HumanoidRootPart")
	-- Path following from the monster's cell towards the start cell.
	assert(monster:followPathTo(layout:cellCenter(layout.startCell)))
	local shadow = Shadow.new(forest)
	shadow:step(0.05, 1)
	-- Force-appear next to a fake target to exercise placement.
	local fakeRoot = roblox.Instance.new("Part")
	fakeRoot.CFrame = roblox.CFrame.new(forest.minX + 100, 3, forest.path[1].Z)
	fakeRoot.Position = fakeRoot.CFrame.Position
	shadow:appear({ player = nil, root = fakeRoot, head = fakeRoot }, 45)
	assert(shadow.model.Parent == forest.folder)
	local d = (shadow.position - roblox.Vector3.new(fakeRoot.Position.X, 0, fakeRoot.Position.Z)).Magnitude
	assert(d > 1 and d <= 46, "appear distance " .. d)
	assert(shadow:isSeenBy({ root = fakeRoot, head = fakeRoot }) ~= nil)

	local parts, textures, decals = 0, 0, 0
	for _, desc in Workspace:GetDescendants() do
		if desc:IsA("BasePart") then
			parts += 1
		end
		if desc:IsA("Texture") then
			textures += 1
		elseif desc:IsA("Decal") then
			decals += 1
		end
	end
	print(
		string.format(
			"seed %d: parts=%d textures=%d decals=%d terrainOps=%d moves=%d tweens=%d",
			seed,
			parts,
			textures,
			decals,
			#terrainCalls,
			moves,
			tweens
		)
	)

	monster:destroy()
	shadow:destroy()
	layout.folder:Destroy()
	forest:destroy()
	assert(Workspace:FindFirstChild("Maze") == nil and Workspace:FindFirstChild("Forest") == nil)
end

-- Lune's CFrame.lookAt returns a mirrored frame, so tests face characters via Angles.
local function facing(position, direction)
	return roblox.CFrame.new(position) * roblox.CFrame.Angles(0, math.atan2(-direction.X, -direction.Z), 0)
end

-- Chase + catch: a player standing a few studs from the monster gets caught.
do
	local rng = Random.new(42)
	local layout = MapBuilder.buildMaze(rng)
	local forest = ForestBuilder.build(rng, layout.forestEntry)
	local monster = Monster.new(layout)
	syncPositions(monster.model)

	local function fakeCharacter(name, position, look)
		local attributes = {}
		local player = {
			Name = name,
			GetAttribute = function(_, key)
				return attributes[key]
			end,
			SetAttribute = function(_, key, value)
				attributes[key] = value
			end,
		}
		local character = roblox.Instance.new("Model")
		local root = roblox.Instance.new("Part")
		root.Name = "HumanoidRootPart"
		root.CFrame = facing(position, look)
		root.Position = position
		root.AssemblyLinearVelocity = roblox.Vector3.zero
		root.Parent = character
		local head = roblox.Instance.new("Part")
		head.Name = "Head"
		head.CFrame = roblox.CFrame.new(position + roblox.Vector3.new(0, 1.5, 0))
		head.Position = head.CFrame.Position
		head.Parent = character
		local humanoid = roblox.Instance.new("Humanoid")
		humanoid.Health = 100
		humanoid.Parent = character
		character.Parent = Workspace
		player.Character = character
		player:SetAttribute("InRound", true)
		return player, humanoid
	end

	local near = monster.root.Position + roblox.Vector3.new(3, -2, 0)
	local victim, humanoid = fakeCharacter("Victim", near, roblox.Vector3.new(1, 0, 0))
	victim:SetAttribute("Zone", "Maze")
	fakePlayers = { victim }
	monster:step()
	assert(humanoid.Health == 0, "monster should catch nearby player")
	assert(victim:GetAttribute("InRound") == false)
	assert(fired[1][1] == "Jumpscare" and fired[1][3] == "Monster", "jumpscare fired")
	print("monster catch ok")

	-- Shadow: stalks when not observed, freezes and vanishes when stared at.
	local shadow = Shadow.new(forest)
	local spot = roblox.Vector3.new(forest.minX + 150, 3, forest.path[1].Z)
	local walker, walkerHumanoid = fakeCharacter("Walker", spot, roblox.Vector3.new(1, 0, 0))
	walker:SetAttribute("Zone", "Forest")
	fakePlayers = { walker }
	shadow:step(0.05, 100) -- no reappear yet: sets timer
	shadow:step(0.05, 100 + 20) -- appears behind the walker
	assert(shadow.visible, "shadow should appear")
	local before = shadow.position
	shadow:step(1, 121) -- walker looks away (+X), shadow is behind -> approaches
	assert((shadow.position - before).Magnitude > 5, "shadow should approach when unobserved")
	-- Turn walker to face the shadow: it must freeze, then vanish after StareTime.
	local rootPart = walker.Character.HumanoidRootPart
	local toShadow = (shadow.position - roblox.Vector3.new(spot.X, 0, spot.Z)).Unit
	rootPart.CFrame = facing(spot, toShadow)
	local frozen = shadow.position
	shadow:step(1, 122)
	assert((shadow.position - frozen).Magnitude < 0.01, "shadow should freeze when observed")
	shadow:step(2, 124)
	assert(not shadow.visible, "shadow should vanish after being stared at")
	-- Unobserved long enough -> catches.
	rootPart.CFrame = facing(spot, -toShadow)
	shadow:appear({ player = walker, root = rootPart, head = walker.Character.Head }, 10)
	for i = 1, 40 do
		if walkerHumanoid.Health == 0 then
			break
		end
		shadow:step(0.1, 200 + i * 0.1)
	end
	assert(walkerHumanoid.Health == 0, "shadow should catch unobserved player")
	print("shadow behaviour ok")
end
print("SMOKE OK")
