-- Тёмный лес за выходом из подвала: земля из терраина, извилистая тропа,
-- мёртвые деревья и ели, генератор, забор с воротами и машина на дороге.
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local TweenService = game:GetService("TweenService")
local Workspace = game:GetService("Workspace")

local Config = require(ReplicatedStorage.Shared.Config)
local Build = require(script.Parent.Build)
local Textures = require(script.Parent.Textures)

local FOREST = Config.Forest
local COLORS = Config.Colors
local FENCE_HEIGHT = 12
local GATE_WIDTH = 14

local create = Build.part

local ForestBuilder = {}

local Forest = {}
Forest.__index = Forest

-- Расстояние от точки до отрезка ab в плоскости XZ.
local function distanceToSegment(point, a, b)
	local ab = Vector2.new(b.X - a.X, b.Z - a.Z)
	local ap = Vector2.new(point.X - a.X, point.Z - a.Z)
	local t = math.clamp(ap:Dot(ab) / ab:Dot(ab), 0, 1)
	return (ap - ab * t).Magnitude
end

function Forest:distanceToPath(point)
	local best = math.huge
	for i = 2, #self.path do
		best = math.min(best, distanceToSegment(point, self.path[i - 1], self.path[i]))
	end
	return best
end

function Forest:contains(point, margin)
	return point.X >= self.minX + margin
		and point.X <= self.gateX - margin
		and point.Z >= self.minZ + margin
		and point.Z <= self.maxZ - margin
end

-- Точка на тропе на доле t (0..1) её длины.
function Forest:pathPoint(t)
	local scaled = t * (#self.path - 1)
	local i = math.clamp(math.floor(scaled) + 1, 1, #self.path - 1)
	return self.path[i]:Lerp(self.path[i + 1], scaled - (i - 1))
end

local function deadTree(folder, rng, base)
	local height = rng:NextNumber(18, 30)
	local diameter = rng:NextNumber(1.3, 2.3)
	local trunk = Build.cylinder(folder, base - Vector3.new(0, 1, 0), base + Vector3.new(0, height, 0), diameter, {
		Name = "Trunk",
		Color = COLORS.Bark,
		Material = Enum.Material.Wood,
	})
	Textures.apply(trunk, "Bark", { Enum.NormalId.Top, Enum.NormalId.Bottom, Enum.NormalId.Front, Enum.NormalId.Back })
	for _ = 1, rng:NextInteger(2, 4) do
		local start = base + Vector3.new(0, height * rng:NextNumber(0.45, 0.9), 0)
		local yaw, tilt = rng:NextNumber(0, math.pi * 2), math.rad(rng:NextNumber(30, 65))
		local direction = Vector3.new(math.cos(yaw) * math.sin(tilt), math.cos(tilt), math.sin(yaw) * math.sin(tilt))
		Build.cylinder(folder, start, start + direction * rng:NextNumber(5, 10), rng:NextNumber(0.4, 0.8), {
			Name = "Branch",
			Color = COLORS.Bark,
			Material = Enum.Material.Wood,
			CanCollide = false,
		})
	end
	return { base = base, radius = diameter / 2 }
end

local function pineTree(folder, rng, base)
	local trunkHeight = rng:NextNumber(5, 8)
	Build.cylinder(folder, base - Vector3.new(0, 1, 0), base + Vector3.new(0, trunkHeight, 0), 1.4, {
		Name = "Trunk",
		Color = COLORS.Bark,
		Material = Enum.Material.Wood,
	})
	local width = rng:NextNumber(10, 14)
	local tiers = rng:NextInteger(4, 5)
	for tier = 0, tiers - 1 do
		local size = width * (1 - tier / (tiers + 0.5))
		create("Part", folder, {
			Name = "Needles",
			Size = Vector3.new(size, 3.5, size),
			CFrame = CFrame.new(base + Vector3.new(0, trunkHeight + tier * 3.4, 0))
				* CFrame.Angles(0, tier * math.pi / 4 + rng:NextNumber(0, 0.3), 0),
			Color = COLORS.Pine,
			Material = Enum.Material.Grass,
			CanCollide = false,
		})
	end
end

local function poster(folder, rng, tree)
	local yaw = rng:NextNumber(0, math.pi * 2)
	local outward = Vector3.new(math.cos(yaw), 0, math.sin(yaw))
	local position = tree.base + Vector3.new(0, 5, 0) + outward * (tree.radius + 0.06)
	local paper = create("Part", folder, {
		Name = "Poster",
		Size = Vector3.new(1.8, 2.4, 0.05),
		CFrame = CFrame.lookAt(position, position + outward) * CFrame.Angles(0, 0, rng:NextNumber(-0.15, 0.15)),
		Color = Color3.fromRGB(200, 195, 175),
		Material = Enum.Material.SmoothPlastic,
		CanCollide = false,
	})
	if not Textures.decal(paper, "Poster", Enum.NormalId.Front) then
		Build.surfaceText(paper, Enum.NormalId.Front, {
			{ text = "ПРОПАЛ", height = 0.25, color = Color3.fromRGB(20, 20, 20) },
			{ text = "?", height = 0.45, color = Color3.fromRGB(60, 60, 60) },
			{ text = "НЕ ХОДИТЕ В ЛЕС НОЧЬЮ", height = 0.12, color = Color3.fromRGB(110, 0, 0) },
		}, 1)
	end
end

local function lampPost(folder, position)
	create("Part", folder, {
		Name = "LampPost",
		Size = Vector3.new(0.6, 10, 0.6),
		CFrame = CFrame.new(position + Vector3.new(0, 5, 0)),
		Color = COLORS.Bark,
		Material = Enum.Material.Wood,
	})
	local head = create("Part", folder, {
		Name = "PathLamp",
		Size = Vector3.new(1.4, 1, 1.4),
		CFrame = CFrame.new(position + Vector3.new(0, 10.5, 0)),
		Color = COLORS.LampOff,
		Material = Enum.Material.Glass,
		CanQuery = false,
	})
	Build.light(
		head,
		"PointLight",
		{ Range = 26, Brightness = 1.2, Color = COLORS.Lamp, Shadows = true, Enabled = false }
	)
	return head
end

local function buildGenerator(folder, position)
	local body = create("Part", folder, {
		Name = "Generator",
		Size = Vector3.new(5, 3.5, 3.5),
		CFrame = CFrame.new(position + Vector3.new(0, 1.75, 0)),
		Color = COLORS.Generator,
		Material = Enum.Material.CorrodedMetal,
	})
	create("Part", folder, {
		Name = "Panel",
		Size = Vector3.new(2, 1.2, 0.2),
		CFrame = CFrame.new(position + Vector3.new(0.8, 2, -1.85)),
		Color = COLORS.Metal,
		Material = Enum.Material.Metal,
	})
	Build.cylinder(
		folder,
		position + Vector3.new(-1.6, 3.5, 0.8),
		position + Vector3.new(-1.6, 5.5, 0.8),
		0.6,
		{ Name = "Exhaust", Color = COLORS.Metal, Material = Enum.Material.CorrodedMetal }
	)
	-- Мигающий фонарь рядом — чтобы генератор можно было найти в темноте.
	create("Part", folder, {
		Name = "LanternPole",
		Size = Vector3.new(0.4, 7, 0.4),
		CFrame = CFrame.new(position + Vector3.new(3.5, 3.5, 0)),
		Color = COLORS.Bark,
		Material = Enum.Material.Wood,
	})
	local lantern = create("Part", folder, {
		Name = "Lantern",
		Size = Vector3.new(0.8, 1, 0.8),
		CFrame = CFrame.new(position + Vector3.new(3.5, 7.4, 0)),
		Color = Color3.fromRGB(255, 150, 60),
		Material = Enum.Material.Neon,
		CanCollide = false,
		CanQuery = false,
	}, "FlickerLight")
	Build.light(lantern, "PointLight", { Range = 18, Brightness = 1.2, Color = Color3.fromRGB(255, 150, 60) })
	return body
end

local function buildFenceAndGate(forest, folder)
	local x, gateZ = forest.gateX, forest.gateZ
	local gate0, gate1 = gateZ - GATE_WIDTH / 2, gateZ + GATE_WIDTH / 2
	-- Две секции забора: от края леса до ворот и от ворот до другого края.
	for _, span in { { forest.minZ, gate0 }, { gate1, forest.maxZ } } do
		local z0, z1 = span[1], span[2]
		local length = z1 - z0
		if length > 0 then
			local center = (z0 + z1) / 2
			for z = z0, z1, 8 do
				create("Part", folder, {
					Name = "FencePost",
					Size = Vector3.new(0.6, FENCE_HEIGHT, 0.6),
					CFrame = CFrame.new(x, FENCE_HEIGHT / 2, z),
					Color = COLORS.Metal,
					Material = Enum.Material.CorrodedMetal,
				})
			end
			for _, height in { 1.5, FENCE_HEIGHT / 2, FENCE_HEIGHT - 0.3 } do
				create("Part", folder, {
					Name = "FenceRail",
					Size = Vector3.new(0.3, 0.3, length),
					CFrame = CFrame.new(x, height, center),
					Color = COLORS.Metal,
					Material = Enum.Material.CorrodedMetal,
				})
			end
			-- Сетка: невидимая стена (через забор не пролезть) + текстура, если задана.
			local mesh = create("Part", folder, {
				Name = "FenceMesh",
				Size = Vector3.new(0.1, FENCE_HEIGHT, length),
				CFrame = CFrame.new(x, FENCE_HEIGHT / 2, center),
				Transparency = 1,
			})
			Textures.apply(mesh, "Fence", { Enum.NormalId.Left, Enum.NormalId.Right })
		end
	end

	forest.gateLeaves = {}
	for _, side in { -1, 1 } do
		local leaf = create("Part", folder, {
			Name = "GateLeaf",
			Size = Vector3.new(0.6, FENCE_HEIGHT - 2, GATE_WIDTH / 2),
			CFrame = CFrame.new(x, (FENCE_HEIGHT - 2) / 2, gateZ + side * GATE_WIDTH / 4),
			Color = COLORS.Metal,
			Material = Enum.Material.DiamondPlate,
		})
		table.insert(forest.gateLeaves, { part = leaf, side = side })
	end
	local sign = create("Part", folder, {
		Name = "GateSign",
		Size = Vector3.new(0.4, 2.2, GATE_WIDTH),
		CFrame = CFrame.new(x - 0.4, FENCE_HEIGHT + 0.6, gateZ),
		Color = Color3.fromRGB(20, 20, 20),
	})
	local _, labels = Build.surfaceText(sign, Enum.NormalId.Left, {
		{ text = "НЕТ ПИТАНИЯ · ГЕНЕРАТОР В ЛЕСУ", height = 0.8, color = COLORS.MonsterEyes },
	}, 0)
	forest.gateLabel = labels[1]
end

local function buildRoadAndCar(forest, folder)
	local roadX = forest.gateX + 14
	create("Part", folder, {
		Name = "Road",
		Size = Vector3.new(16, 1, forest.maxZ - forest.minZ + 80),
		CFrame = CFrame.new(roadX, -0.45, (forest.minZ + forest.maxZ) / 2),
		Color = Color3.fromRGB(30, 30, 32),
		Material = Enum.Material.Asphalt,
	})
	-- Машина стоит вдоль дороги, фарами на юг (+Z).
	local base = Vector3.new(roadX - 3, 0, forest.gateZ + 4)
	local body = create("Part", folder, {
		Name = "Car",
		Size = Vector3.new(6, 2.2, 12),
		CFrame = CFrame.new(base + Vector3.new(0, 2.1, 0)),
		Color = COLORS.Car,
		Material = Enum.Material.Metal,
	})
	create("Part", folder, {
		Name = "CarCabin",
		Size = Vector3.new(5.6, 2, 6),
		CFrame = CFrame.new(base + Vector3.new(0, 4.2, -1)),
		Color = Color3.fromRGB(20, 24, 28),
		Material = Enum.Material.Glass,
		Transparency = 0.2,
	})
	for _, wheel in { { -3, -4 }, { 3, -4 }, { -3, 4 }, { 3, 4 } } do
		local center = base + Vector3.new(wheel[1], 1.2, wheel[2])
		Build.cylinder(folder, center - Vector3.new(0.5, 0, 0), center + Vector3.new(0.5, 0, 0), 2.4, {
			Name = "Wheel",
			Color = Color3.fromRGB(15, 15, 15),
			Material = Enum.Material.Rubber,
		})
	end
	for _, side in { -2, 2 } do
		local headlight = create("Part", folder, {
			Name = "Headlight",
			Size = Vector3.new(1, 0.6, 0.2),
			CFrame = CFrame.new(base + Vector3.new(side, 2.4, 6.05)),
			Color = Color3.fromRGB(255, 250, 220),
			Material = Enum.Material.Neon,
			CanCollide = false,
		})
		-- Front у детали смотрит на -Z, поэтому свет направлен на Back (+Z).
		Build.light(headlight, "SpotLight", { Face = Enum.NormalId.Back, Range = 50, Angle = 60, Brightness = 4 })
		create("Part", folder, {
			Name = "Taillight",
			Size = Vector3.new(1, 0.5, 0.2),
			CFrame = CFrame.new(base + Vector3.new(side, 2.4, -6.05)),
			Color = COLORS.MonsterEyes,
			Material = Enum.Material.Neon,
			CanCollide = false,
		})
	end
	return body
end

-- Невидимые стены по краям леса (в западной — проход из коридора подвала).
local function buildBounds(forest, folder, entry)
	local height = 80
	local east = forest.gateX + 30
	local function wall(center, size)
		create("Part", folder, {
			Name = "Boundary",
			Size = size,
			CFrame = CFrame.new(center),
			Transparency = 1,
			CanQuery = false,
		})
	end
	local lengthX = east - forest.minX
	wall(Vector3.new(forest.minX + lengthX / 2, height / 2, forest.minZ - 0.5), Vector3.new(lengthX, height, 1))
	wall(Vector3.new(forest.minX + lengthX / 2, height / 2, forest.maxZ + 0.5), Vector3.new(lengthX, height, 1))
	wall(
		Vector3.new(east + 0.5, height / 2, (forest.minZ + forest.maxZ) / 2),
		Vector3.new(1, height, forest.maxZ - forest.minZ)
	)
	local half = Config.Maze.CellSize / 2
	local northLength = entry.Z - half - forest.minZ
	local southLength = forest.maxZ - (entry.Z + half)
	wall(Vector3.new(forest.minX - 0.5, height / 2, forest.minZ + northLength / 2), Vector3.new(1, height, northLength))
	wall(Vector3.new(forest.minX - 0.5, height / 2, forest.maxZ - southLength / 2), Vector3.new(1, height, southLength))
end

-- entry — точка, где коридор подвала выходит в лес (западный край леса).
function ForestBuilder.build(rng, entry)
	local folder = Instance.new("Folder")
	folder.Name = "Forest"
	-- В Trees лежит всё, что закрывает обзор Тени и игрокам.
	local trees = Instance.new("Folder")
	trees.Name = "Trees"
	trees.Parent = folder

	local forest = setmetatable({
		folder = folder,
		trees = trees,
		minX = entry.X,
		gateX = entry.X + FOREST.Length,
		minZ = entry.Z - FOREST.Width / 2,
		maxZ = entry.Z + FOREST.Width / 2,
	}, Forest)

	-- Извилистая тропа от выхода из подвала до ворот.
	forest.path = { entry }
	local z = entry.Z
	for i = 1, FOREST.PathSegments do
		z = math.clamp(z + rng:NextNumber(-40, 40), forest.minZ + 35, forest.maxZ - 35)
		table.insert(forest.path, Vector3.new(entry.X + FOREST.Length * i / FOREST.PathSegments, 0, z))
	end
	forest.gateZ = z

	-- Земля: терраин (трава, листва, грязь) — у встроенных материалов Roblox уже есть текстуры.
	local terrain = Workspace.Terrain
	terrain:SetMaterialColor(Enum.Material.Grass, COLORS.Grass)
	terrain:SetMaterialColor(Enum.Material.LeafyGrass, COLORS.LeafyGrass)
	terrain:SetMaterialColor(Enum.Material.Mud, COLORS.Mud)
	-- Поверхность земли на высоте 0, как пол подвала. Западнее входа (под зданием
	-- и коридором) земля на 1 стад ниже, чтобы не просвечивать сквозь их пол.
	local eastX, westX = forest.gateX + 40, forest.minX - 24
	local depthZ = FOREST.Width + 40
	terrain:FillBlock(
		CFrame.new((forest.minX + eastX) / 2, -4, entry.Z),
		Vector3.new(eastX - forest.minX, 8, depthZ),
		Enum.Material.Grass
	)
	terrain:FillBlock(
		CFrame.new((westX + forest.minX) / 2, -4.5, entry.Z),
		Vector3.new(forest.minX - westX, 7, depthZ),
		Enum.Material.Grass
	)
	forest.terrainCFrame = CFrame.new((westX + eastX) / 2, -4, entry.Z)
	forest.terrainSize = Vector3.new(eastX - westX, 16, depthZ)

	for _ = 1, 25 do
		local patch = Vector3.new(
			rng:NextNumber(forest.minX + 16, forest.gateX - 16),
			-2,
			rng:NextNumber(forest.minZ + 16, forest.maxZ - 16)
		)
		local size = rng:NextNumber(12, 30)
		terrain:FillBlock(
			CFrame.new(patch) * CFrame.Angles(0, rng:NextNumber(0, math.pi), 0),
			Vector3.new(size, 4, size * rng:NextNumber(0.5, 1)),
			Enum.Material.LeafyGrass
		)
	end
	for i = 2, #forest.path do
		local a, b = forest.path[i - 1], forest.path[i]
		local direction = (b - a).Unit
		-- Первый отрезок не заходит назад в коридор подвала.
		local from = if i == 2 then a else a - direction * (FOREST.PathWidth / 2)
		local to = b + direction * (FOREST.PathWidth / 2)
		local down = Vector3.new(0, 2, 0)
		terrain:FillBlock(
			CFrame.lookAt((from + to) / 2 - down, to - down),
			Vector3.new(FOREST.PathWidth, 4, (to - from).Magnitude),
			Enum.Material.Mud
		)
	end

	-- Генератор — на поляне в стороне от тропы, где-то в середине леса.
	local anchor = forest:pathPoint(rng:NextNumber(0.4, 0.6))
	local side = rng:NextInteger(0, 1) == 0 and -1 or 1
	local generatorPosition =
		Vector3.new(anchor.X + rng:NextNumber(-20, 20), 0, anchor.Z + side * rng:NextNumber(40, 60))
	generatorPosition =
		Vector3.new(generatorPosition.X, 0, math.clamp(generatorPosition.Z, forest.minZ + 20, forest.maxZ - 20))
	forest.generator = buildGenerator(folder, generatorPosition)

	-- Деревья: случайные точки, кроме тропы, полян и уже занятых мест.
	local placed = {}
	local function isFree(point, spacing)
		if not forest:contains(point, 4) then
			return false
		end
		if forest:distanceToPath(point) < FOREST.PathWidth / 2 + 4 then
			return false
		end
		local clearings = {
			{ generatorPosition, 14 },
			{ entry, 16 },
			{ Vector3.new(forest.gateX, 0, forest.gateZ), 20 },
		}
		for _, clearing in clearings do
			if (point - clearing[1]).Magnitude < clearing[2] then
				return false
			end
		end
		for _, other in placed do
			if (point - other).Magnitude < spacing then
				return false
			end
		end
		return true
	end

	local deadTrees = {}
	local attempts = 0
	while #placed < FOREST.TreeCount and attempts < FOREST.TreeCount * 8 do
		attempts += 1
		local point =
			Vector3.new(rng:NextNumber(forest.minX, forest.gateX), 0, rng:NextNumber(forest.minZ, forest.maxZ))
		if isFree(point, 7) then
			table.insert(placed, point)
			if rng:NextNumber() < 0.55 then
				table.insert(deadTrees, deadTree(trees, rng, point))
			else
				pineTree(trees, rng, point)
			end
		end
	end

	-- Поваленные брёвна.
	for _ = 1, FOREST.Logs do
		local point =
			Vector3.new(rng:NextNumber(forest.minX, forest.gateX), 0, rng:NextNumber(forest.minZ, forest.maxZ))
		if isFree(point, 6) then
			local yaw = rng:NextNumber(0, math.pi * 2)
			local half = Vector3.new(math.cos(yaw), 0, math.sin(yaw)) * rng:NextNumber(5, 8)
			local diameter = rng:NextNumber(1.2, 1.8)
			local lift = Vector3.new(0, diameter / 2 - 0.1, 0)
			Build.cylinder(trees, point - half + lift, point + half + lift, diameter, {
				Name = "Log",
				Color = COLORS.Bark,
				Material = Enum.Material.Wood,
			})
			table.insert(placed, point)
		end
	end

	-- Объявления о пропавших на мёртвых деревьях.
	Build.shuffle(deadTrees, rng)
	for k = 1, math.min(FOREST.Posters, #deadTrees) do
		poster(folder, rng, deadTrees[k])
	end

	-- Фонари вдоль тропы (выключены до запуска генератора).
	forest.lamps = {}
	local pathLength = 0
	for i = 2, #forest.path do
		pathLength += (forest.path[i] - forest.path[i - 1]).Magnitude
	end
	local lampCount = math.floor(pathLength / FOREST.LampSpacing)
	for k = 1, lampCount do
		local t = k / (lampCount + 1)
		local point = forest:pathPoint(t)
		local ahead = forest:pathPoint(math.min(1, t + 0.01))
		local direction = Vector3.new(ahead.X - point.X, 0, ahead.Z - point.Z).Unit
		local sideOffset = Vector3.new(-direction.Z, 0, direction.X)
			* (FOREST.PathWidth / 2 + 1.5)
			* (k % 2 == 0 and 1 or -1)
		table.insert(forest.lamps, lampPost(folder, point + sideOffset))
	end

	buildFenceAndGate(forest, folder)
	forest.car = buildRoadAndCar(forest, folder)
	buildBounds(forest, folder, entry)

	folder.Parent = Workspace
	return forest
end

-- Генератор запущен: фонари загораются, ворота разъезжаются.
function Forest:powerOn()
	for _, lamp in self.lamps do
		lamp.Material = Enum.Material.Neon
		lamp.Color = COLORS.Lamp
		lamp:FindFirstChildOfClass("PointLight").Enabled = true
	end
	for _, leaf in self.gateLeaves do
		local target = leaf.part.CFrame + Vector3.new(0, 0, leaf.side * (GATE_WIDTH / 2 - 0.5))
		TweenService:Create(leaf.part, TweenInfo.new(3, Enum.EasingStyle.Quad), { CFrame = target }):Play()
	end
	self.gateLabel.Text = "ВЫЕЗД ОТКРЫТ"
	self.gateLabel.TextColor3 = COLORS.DoorOpen
	Build.light(self.generator, "PointLight", { Range = 14, Brightness = 1, Color = Color3.fromRGB(255, 200, 120) })
end

-- Убирает лес вместе с терраином.
function Forest:destroy()
	Workspace.Terrain:FillBlock(self.terrainCFrame, self.terrainSize, Enum.Material.Air)
	self.folder:Destroy()
end

return ForestBuilder
