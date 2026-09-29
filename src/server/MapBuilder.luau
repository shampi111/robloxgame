-- Строит из деталей лобби (один раз) и лабиринт-подвал (заново каждый раунд).
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local Workspace = game:GetService("Workspace")

local Config = require(ReplicatedStorage.Shared.Config)
local Build = require(script.Parent.Build)
local Maze = require(script.Parent.Maze)
local Textures = require(script.Parent.Textures)

local MAZE = Config.Maze
local COLORS = Config.Colors
local LOBBY_CENTER = Vector3.new(0, 400, 0) -- лобби висит высоко над картой
local LOBBY_SIZE = Vector3.new(40, 14, 40)

local create = Build.part

local MapBuilder = {}

-- Отключаем чужие SpawnLocation (например, из шаблона Baseplate),
-- чтобы игроки появлялись только в лобби.
local function disableOtherSpawns(except)
	for _, descendant in Workspace:GetDescendants() do
		if descendant:IsA("SpawnLocation") and descendant ~= except then
			descendant.Enabled = false
		end
	end
end

function MapBuilder.buildLobby()
	local folder = Instance.new("Folder")
	folder.Name = "Lobby"
	local center, size = LOBBY_CENTER, LOBBY_SIZE

	create("Part", folder, {
		Name = "Floor",
		Size = Vector3.new(size.X, 1, size.Z),
		CFrame = CFrame.new(center - Vector3.new(0, 0.5, 0)),
		Color = COLORS.LobbyFloor,
		Material = Enum.Material.WoodPlanks,
	})
	create("Part", folder, {
		Name = "Ceiling",
		Size = Vector3.new(size.X, 1, size.Z),
		CFrame = CFrame.new(center + Vector3.new(0, size.Y + 0.5, 0)),
		Color = COLORS.Ceiling,
	})

	local walls = {}
	for _, wall in
		{
			{ Vector3.new(size.X, size.Y, 1), Vector3.new(0, 0, -size.Z / 2 - 0.5) },
			{ Vector3.new(size.X, size.Y, 1), Vector3.new(0, 0, size.Z / 2 + 0.5) },
			{ Vector3.new(1, size.Y, size.Z), Vector3.new(-size.X / 2 - 0.5, 0, 0) },
			{ Vector3.new(1, size.Y, size.Z), Vector3.new(size.X / 2 + 0.5, 0, 0) },
		}
	do
		table.insert(
			walls,
			create("Part", folder, {
				Name = "Wall",
				Size = wall[1],
				CFrame = CFrame.new(center + wall[2] + Vector3.new(0, size.Y / 2, 0)),
				Color = COLORS.LobbyWall,
				Material = Enum.Material.Brick,
			})
		)
	end

	-- Правила на северной стене (её внутренняя сторона смотрит на +Z, то есть Back).
	Build.surfaceText(walls[1], Enum.NormalId.Back, {
		{ text = "ПОБЕГ", height = 0.26, color = COLORS.MonsterEyes },
		{
			text = "1. Подвал: найдите все ключи и откройте выход.",
			height = 0.1,
			color = Color3.new(1, 1, 1),
		},
		{
			text = "2. Лес: запустите генератор и уезжайте на машине.",
			height = 0.1,
			color = Color3.new(1, 1, 1),
		},
		{
			text = "В подвале ОН видит и слышит. В лесу — не отводите взгляд.",
			height = 0.1,
			color = COLORS.Lamp,
		},
		{ text = "F — фонарь   ·   Shift — бег (шумно!)", height = 0.09, color = COLORS.Lamp },
	}, 0)

	local lamp = create("Part", folder, {
		Name = "Lamp",
		Size = Vector3.new(4, 0.4, 4),
		CFrame = CFrame.new(center + Vector3.new(0, size.Y - 0.2, 0)),
		Color = COLORS.Lamp,
		Material = Enum.Material.Neon,
		CanCollide = false,
	})
	Build.light(lamp, "PointLight", { Range = 40, Brightness = 1.5, Color = COLORS.Lamp, Shadows = true })

	local spawn = create("SpawnLocation", folder, {
		Name = "LobbySpawn",
		Size = Vector3.new(8, 1, 8),
		CFrame = CFrame.new(center + Vector3.new(0, -0.4, 6)),
		Color = COLORS.LobbyFloor:Lerp(Color3.new(0, 0, 0), 0.3),
		Material = Enum.Material.WoodPlanks,
		Duration = 0,
		Neutral = true,
	})

	folder.Parent = Workspace
	disableOtherSpawns(spawn)
	return { folder = folder, spawn = spawn }
end

-- Лабиринт в мире: клетка (x, y) занимает квадрат от (x, y) * CellSize, пол на высоте 0.
local Layout = {}
Layout.__index = Layout

function Layout:cellCenter(i)
	local x, y = self.maze:coords(i)
	return Vector3.new((x + 0.5) * self.cellSize, 0, (y + 0.5) * self.cellSize)
end

function Layout:cellAt(position)
	local x = math.clamp(math.floor(position.X / self.cellSize), 0, self.maze.width - 1)
	local y = math.clamp(math.floor(position.Z / self.cellSize), 0, self.maze.height - 1)
	return self.maze:index(x, y)
end

-- Точки появления игроков: сетка 3×3 вокруг центра стартовой клетки.
function Layout:startPosition(playerIndex)
	local slot = (playerIndex - 1) % 9
	local offset = Vector3.new((slot % 3 - 1) * 3.5, 3, (slot // 3 - 1) * 3.5)
	return self:cellCenter(self.startCell) + offset
end

function MapBuilder.buildMaze(rng)
	local maze = Maze.generate(MAZE.Width, MAZE.Height, rng, MAZE.ExtraOpenings)
	local cell, wallHeight = MAZE.CellSize, MAZE.WallHeight
	local sizeX, sizeZ = MAZE.Width * cell, MAZE.Height * cell

	local folder = Instance.new("Folder")
	folder.Name = "Maze"
	-- В Walls лежит всё, что загораживает обзор монстру.
	local walls = Instance.new("Folder")
	walls.Name = "Walls"
	walls.Parent = folder

	local layout = setmetatable({
		maze = maze,
		folder = folder,
		walls = walls,
		cellSize = cell,
		startCell = 1,
		exitCell = maze:index(MAZE.Width - 1, MAZE.Height - 1),
	}, Layout)

	local floor = create("Part", folder, {
		Name = "Floor",
		Size = Vector3.new(sizeX + 2, 1, sizeZ + 2),
		CFrame = CFrame.new(sizeX / 2, -0.5, sizeZ / 2),
		Color = COLORS.Floor,
		Material = Enum.Material.Concrete,
	})
	Textures.apply(floor, "MazeFloor", { Enum.NormalId.Top })
	create("Part", folder, {
		Name = "Ceiling",
		Size = Vector3.new(sizeX + 2, 1, sizeZ + 2),
		CFrame = CFrame.new(sizeX / 2, wallHeight + 0.5, sizeZ / 2),
		Color = COLORS.Ceiling,
		Material = Enum.Material.Concrete,
	})

	-- Стены идут от узла сетки до узла, в узлах стоят колонны — так нет щелей и мерцания.
	local pillars = {}
	local function pillar(x, z)
		local key = x .. ":" .. z
		if pillars[key] then
			return
		end
		pillars[key] = true
		create("Part", walls, {
			Name = "Pillar",
			Size = Vector3.new(1.4, wallHeight, 1.4),
			CFrame = CFrame.new(x, wallHeight / 2, z),
			Color = COLORS.Pillar,
			Material = Enum.Material.Concrete,
		})
	end

	local visibleFaces = {} -- { part, face } — стороны стен, видимые изнутри
	-- faces — стороны стены, которые видны изнутри лабиринта.
	local function wall(ax, az, bx, bz, faces)
		local alongX = az == bz
		local length = alongX and math.abs(bx - ax) or math.abs(bz - az)
		local part = create("Part", walls, {
			Name = "Wall",
			Size = alongX and Vector3.new(length, wallHeight, 1) or Vector3.new(1, wallHeight, length),
			CFrame = CFrame.new((ax + bx) / 2, wallHeight / 2, (az + bz) / 2),
			Color = COLORS.Wall,
			Material = Enum.Material.Concrete,
		})
		pillar(ax, az)
		pillar(bx, bz)
		Textures.apply(part, "MazeWall", faces)
		for _, face in faces do
			table.insert(visibleFaces, { part = part, face = face })
		end
		return part
	end

	local BOTH_X = { Enum.NormalId.Left, Enum.NormalId.Right }
	local BOTH_Z = { Enum.NormalId.Front, Enum.NormalId.Back }
	for i = 1, MAZE.Width * MAZE.Height do
		local x, y = maze:coords(i)
		local x0, x1, z0, z1 = x * cell, (x + 1) * cell, y * cell, (y + 1) * cell
		if x == 0 then
			wall(x0, z0, x0, z1, { Enum.NormalId.Right })
		end
		if y == 0 then
			wall(x0, z0, x1, z0, { Enum.NormalId.Back })
		end
		if x == MAZE.Width - 1 then
			if i ~= layout.exitCell then
				wall(x1, z0, x1, z1, { Enum.NormalId.Left })
			end
		elseif not maze:isLinked(i, i + 1) then
			wall(x1, z0, x1, z1, BOTH_X)
		end
		if y == MAZE.Height - 1 then
			wall(x0, z1, x1, z1, { Enum.NormalId.Front })
		elseif not maze:isLinked(i, i + MAZE.Width) then
			wall(x0, z1, x1, z1, BOTH_Z)
		end
	end

	-- Надписи на стенах. LightInfluence = 1: в темноте их не видно, только под фонарём.
	-- Если задана текстура Scratches, часть надписей заменяется следами когтей.
	Build.shuffle(visibleFaces, rng)
	for k = 1, math.min(MAZE.WallWritings, #visibleFaces) do
		local target = visibleFaces[k]
		if k % 2 == 0 and Textures.decal(target.part, "Scratches", target.face) then
			continue
		end
		Build.surfaceText(target.part, target.face, {
			{
				text = Config.WallWritings[rng:NextInteger(1, #Config.WallWritings)],
				height = 0.35,
				color = COLORS.Writing,
				rotation = rng:NextNumber(-8, 8),
			},
		}, 1)
	end

	-- Пятна на полу (только если задана текстура Blood).
	if Textures.get("Blood") then
		for _ = 1, 6 do
			local position = layout:cellCenter(rng:NextInteger(2, MAZE.Width * MAZE.Height))
			local stain = create("Part", folder, {
				Name = "Stain",
				Size = Vector3.new(6, 0.05, 6),
				CFrame = CFrame.new(position + Vector3.new(rng:NextNumber(-4, 4), 0.03, rng:NextNumber(-4, 4)))
					* CFrame.Angles(0, rng:NextNumber(0, math.pi * 2), 0),
				Transparency = 1,
				CanCollide = false,
				CanQuery = false,
				CanTouch = false,
			})
			Textures.decal(stain, "Blood", Enum.NormalId.Top)
		end
	end

	-- Лампы на потолке; в стартовой клетке лампа есть всегда и не мигает.
	for i = 1, MAZE.Width * MAZE.Height do
		if i == layout.startCell or rng:NextNumber() < MAZE.LampChance then
			local lamp = create("Part", folder, {
				Name = "Lamp",
				Size = Vector3.new(3, 0.3, 3),
				CFrame = CFrame.new(layout:cellCenter(i) + Vector3.new(0, wallHeight - 0.15, 0)),
				Color = COLORS.Lamp,
				Material = Enum.Material.Neon,
				CanCollide = false,
				CanQuery = false,
			})
			Build.light(lamp, "PointLight", { Range = 22, Brightness = 0.8, Color = COLORS.Lamp, Shadows = true })
			if i ~= layout.startCell and rng:NextNumber() < MAZE.FlickerChance then
				lamp:AddTag("FlickerLight")
			end
		end
	end

	-- Дверь выхода — в восточной стене последней клетки.
	local exitX, exitZ0, exitZ1 = sizeX, (MAZE.Height - 1) * cell, sizeZ
	local exitZ = (exitZ0 + exitZ1) / 2
	pillar(exitX, exitZ0)
	pillar(exitX, exitZ1)
	layout.door = create("Part", walls, {
		Name = "ExitDoor",
		Size = Vector3.new(1, wallHeight, cell - 1.4),
		CFrame = CFrame.new(exitX, wallHeight / 2, exitZ),
		Color = COLORS.DoorLocked,
		Material = Enum.Material.DiamondPlate,
	})
	Build.surfaceText(layout.door, Enum.NormalId.Left, {
		{ text = "ВЫХОД", height = 0.25, color = COLORS.MonsterEyes },
	}, 0)
	local exitSign = create("Part", folder, {
		Name = "ExitLight",
		Size = Vector3.new(0.4, 0.6, 3),
		CFrame = CFrame.new(exitX - 0.8, wallHeight - 1, exitZ),
		Color = COLORS.MonsterEyes,
		Material = Enum.Material.Neon,
		CanCollide = false,
		CanQuery = false,
	})
	Build.light(exitSign, "PointLight", { Range = 14, Brightness = 1, Color = COLORS.MonsterEyes })

	-- Монстр подвала не может выйти за дверь: барьер сталкивается только с ним.
	create("Part", folder, {
		Name = "MonsterBarrier",
		Size = Vector3.new(2, wallHeight, cell),
		CFrame = CFrame.new(exitX + 1.5, wallHeight / 2, exitZ),
		Transparency = 1,
		CanQuery = false,
		CanTouch = false,
		CollisionGroup = "MonsterBarrier",
	})

	-- Короткий коридор за дверью, который выходит в лес.
	local corridorCenter = Vector3.new(exitX + cell / 2, 0, exitZ)
	create("Part", folder, {
		Name = "CorridorFloor",
		Size = Vector3.new(cell, 1, cell),
		CFrame = CFrame.new(corridorCenter - Vector3.new(0, 0.5, 0)),
		Color = COLORS.Floor,
		Material = Enum.Material.Concrete,
	})
	create("Part", folder, {
		Name = "CorridorCeiling",
		Size = Vector3.new(cell, 1, cell),
		CFrame = CFrame.new(corridorCenter + Vector3.new(0, wallHeight + 0.5, 0)),
		Color = COLORS.Ceiling,
	})
	for _, side in { -1, 1 } do
		create("Part", folder, {
			Name = "CorridorWall",
			Size = Vector3.new(cell, wallHeight, 1),
			CFrame = CFrame.new(corridorCenter + Vector3.new(0, wallHeight / 2, side * (cell / 2 + 0.5))),
			Color = COLORS.Wall,
			Material = Enum.Material.Concrete,
		})
	end
	layout.exitZone = create("Part", folder, {
		Name = "ExitZone",
		Size = Vector3.new(cell - 6, wallHeight, cell - 2),
		CFrame = CFrame.new(corridorCenter + Vector3.new(3, wallHeight / 2, 0)),
		Transparency = 1,
		CanCollide = false,
		CanQuery = false,
	})
	layout.forestEntry = Vector3.new(exitX + cell, 0, exitZ)

	-- Ключи — в тупиках подальше от старта; если тупиков мало, в любых дальних клетках.
	local distances = maze:distances(layout.startCell)
	local deadEnds, others = {}, {}
	local isDeadEnd = {}
	for _, i in maze:deadEnds() do
		isDeadEnd[i] = true
	end
	for i = 1, MAZE.Width * MAZE.Height do
		if i ~= layout.startCell and i ~= layout.exitCell and distances[i] >= 3 then
			table.insert(isDeadEnd[i] and deadEnds or others, i)
		end
	end
	local keyCells = Build.shuffle(deadEnds, rng)
	for _, i in Build.shuffle(others, rng) do
		table.insert(keyCells, i)
	end
	layout.keys = {}
	for k = 1, math.min(Config.KeysToEscape, #keyCells) do
		local key = create("Part", folder, {
			Name = "Key",
			Size = Vector3.new(0.3, 0.9, 2),
			CFrame = CFrame.new(layout:cellCenter(keyCells[k]) + Vector3.new(0, 2.5, 0)),
			Color = COLORS.Key,
			Material = Enum.Material.Neon,
			CanCollide = false,
		}, "Spin")
		Build.light(key, "PointLight", { Range = 8, Brightness = 1, Color = COLORS.Key })
		table.insert(layout.keys, key)
	end

	-- Монстр просыпается в дальней части лабиринта.
	local maxDistance = 0
	for _, distance in distances do
		maxDistance = math.max(maxDistance, distance)
	end
	local lairs = {}
	for i, distance in distances do
		if distance >= maxDistance * 0.6 then
			table.insert(lairs, i)
		end
	end
	layout.monsterCell = lairs[rng:NextInteger(1, #lairs)]

	folder.Parent = Workspace
	return layout
end

return MapBuilder
