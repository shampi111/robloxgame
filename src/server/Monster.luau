-- Монстр: бродит по лабиринту, замечает игроков глазами (прямая видимость)
-- и на слух (близко или бегом), преследует и ловит.
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local Workspace = game:GetService("Workspace")

local Config = require(ReplicatedStorage.Shared.Config)
local scare = require(script.Parent.Scare)

local SETTINGS = Config.Monster
local TICK = 0.1
local HIP_HEIGHT = 4 -- от пола до низа HumanoidRootPart

local Monster = {}
Monster.__index = Monster

local function flatDistance(a, b)
	return Vector2.new(a.X - b.X, a.Z - b.Z).Magnitude
end

-- Высокая чёрная фигура с горящими глазами. Все части приварены к HumanoidRootPart.
local function buildModel(floorPosition)
	local model = Instance.new("Model")
	model.Name = "Monster"
	model.ModelStreamingMode = Enum.ModelStreamingMode.Atomic

	local root = Instance.new("Part")
	root.Name = "HumanoidRootPart"
	root.Size = Vector3.new(2, 2, 1)
	root.Transparency = 1
	root.CFrame = CFrame.new(floorPosition + Vector3.new(0, HIP_HEIGHT + 1, 0))
	root.CollisionGroup = "Monster" -- не проходит сквозь MonsterBarrier у выхода
	root.Parent = model

	local function limb(name, size, offset, props)
		local part = Instance.new("Part")
		part.Name = name
		part.Size = size
		part.CFrame = root.CFrame * offset
		part.Color = Config.Colors.MonsterBody
		part.Material = Enum.Material.SmoothPlastic
		part.CanCollide = false
		part.CanQuery = false
		part.CanTouch = false
		part.Massless = true
		for key, value in props or {} do
			part[key] = value
		end
		local weld = Instance.new("WeldConstraint")
		weld.Part0 = root
		weld.Part1 = part
		weld.Parent = part
		part.Parent = model
		return part
	end

	limb("LeftLeg", Vector3.new(0.7, 4, 0.7), CFrame.new(-0.55, -3, 0))
	limb("RightLeg", Vector3.new(0.7, 4, 0.7), CFrame.new(0.55, -3, 0))
	limb("Torso", Vector3.new(2.2, 3.6, 1.1), CFrame.new(0, 0.8, 0))
	limb(
		"LeftArm",
		Vector3.new(0.5, 5.2, 0.5),
		CFrame.new(-1.45, -0.1, -0.2) * CFrame.Angles(math.rad(-8), 0, math.rad(-4))
	)
	limb(
		"RightArm",
		Vector3.new(0.5, 5.2, 0.5),
		CFrame.new(1.45, -0.1, -0.2) * CFrame.Angles(math.rad(-8), 0, math.rad(4))
	)
	local head = limb("Head", Vector3.new(1.5, 1.9, 1.5), CFrame.new(0, 3.6, -0.15))
	for _, x in { -0.35, 0.35 } do
		limb("Eye", Vector3.new(0.35, 0.18, 0.05), CFrame.new(x, 3.8, -0.92), {
			Color = Config.Colors.MonsterEyes,
			Material = Enum.Material.Neon,
		})
	end

	local glow = Instance.new("PointLight")
	glow.Color = Config.Colors.MonsterEyes
	glow.Range = 12
	glow.Brightness = 2
	glow.Parent = head

	if Config.Sounds.Monster ~= "" then
		local sound = Instance.new("Sound")
		sound.SoundId = Config.Sounds.Monster
		sound.Looped = true
		sound.RollOffMaxDistance = 70
		sound.Volume = 1
		sound.Parent = head
		sound:Play()
	end

	local humanoid = Instance.new("Humanoid")
	humanoid.RigType = Enum.HumanoidRigType.R15
	humanoid.HipHeight = HIP_HEIGHT
	humanoid.DisplayDistanceType = Enum.HumanoidDisplayDistanceType.None
	humanoid.HealthDisplayType = Enum.HumanoidHealthDisplayType.AlwaysOff
	humanoid.BreakJointsOnDeath = false
	humanoid.WalkSpeed = SETTINGS.WanderSpeed
	for _, state in
		{
			Enum.HumanoidStateType.Jumping,
			Enum.HumanoidStateType.Climbing,
			Enum.HumanoidStateType.FallingDown,
			Enum.HumanoidStateType.Ragdoll,
			Enum.HumanoidStateType.Swimming,
		}
	do
		humanoid:SetStateEnabled(state, false)
	end
	humanoid.Parent = model

	model.PrimaryPart = root
	model:AddTag("Monster")
	return model, humanoid, root, head
end

function Monster.new(layout)
	local self = setmetatable({}, Monster)
	self.layout = layout
	self.rng = Random.new()
	self.model, self.humanoid, self.root, self.head = buildModel(layout:cellCenter(layout.monsterCell))
	self.model.Parent = layout.folder
	self.root:SetNetworkOwner(nil) -- физикой монстра управляет сервер

	self.rayParams = RaycastParams.new()
	self.rayParams.FilterType = Enum.RaycastFilterType.Include
	self.rayParams.FilterDescendantsInstances = { layout.walls }

	self.route = nil -- { goal, cells, index } — маршрут по клеткам
	self.wanderTarget = nil
	self.lastSeenPosition = nil
	self.lastSeenTime = 0
	self.pausedUntil = 0
	self.directBlockedUntil = 0
	self.progressTime = os.clock()
	self.progressPosition = self.root.Position
	self.chasing = false
	return self
end

function Monster:start()
	self.running = true
	task.spawn(function()
		while self.running and self.model.Parent do
			self:step()
			task.wait(TICK)
		end
	end)
end

function Monster:destroy()
	self.running = false
	self.model:Destroy()
end

-- Живые игроки внутри лабиринта.
function Monster:targets()
	local result = {}
	for _, player in Players:GetPlayers() do
		local character = player.Character
		local humanoid = character and character:FindFirstChildOfClass("Humanoid")
		local root = character and character:FindFirstChild("HumanoidRootPart")
		local inMaze = player:GetAttribute("InRound") and player:GetAttribute("Zone") == "Maze"
		if inMaze and humanoid and humanoid.Health > 0 and root then
			table.insert(result, { player = player, root = root, head = character:FindFirstChild("Head") or root })
		end
	end
	return result
end

function Monster:canSee(part)
	local origin = self.head.Position
	return Workspace:Raycast(origin, part.Position - origin, self.rayParams) == nil
end

-- Ближайший замеченный игрок: (player, rootPart, виден ли напрямую).
function Monster:findTarget()
	local best, bestRoot, bestVisible, bestDistance = nil, nil, false, math.huge
	for _, target in self:targets() do
		local distance = (target.root.Position - self.root.Position).Magnitude
		if distance < bestDistance then
			local velocity = target.root.AssemblyLinearVelocity
			local running = Vector2.new(velocity.X, velocity.Z).Magnitude > Config.WalkSpeed + 2
			local visible = distance <= SETTINGS.SightRange and self:canSee(target.head)
			local heard = distance <= SETTINGS.HearRange or (running and distance <= SETTINGS.RunHearRange)
			if visible or heard then
				best, bestRoot, bestVisible, bestDistance = target.player, target.root, visible, distance
			end
		end
	end
	return best, bestRoot, bestVisible
end

-- Идёт к точке по клеткам лабиринта. Возвращает false, если уже на месте или пути нет.
-- Всегда идём к центру следующей клетки маршрута: две соседние открытые клетки образуют
-- выпуклый прямоугольник, поэтому прямая до центра следующей клетки не задевает стен.
function Monster:followPathTo(position)
	if not position then
		return false
	end
	local layout = self.layout
	local here = layout:cellAt(self.root.Position)
	local goal = layout:cellAt(position)
	if here == goal then
		self.route = nil
		if flatDistance(self.root.Position, position) < 2 then
			return false
		end
		self.humanoid:MoveTo(position)
		return true
	end

	local route = self.route
	if not (route and route.goal == goal and route.index[here]) then
		local cells = layout.maze:path(here, goal)
		if not cells then
			return false
		end
		local index = {}
		for i, cell in cells do
			index[cell] = i
		end
		route = { goal = goal, cells = cells, index = index }
		self.route = route
	end
	self.humanoid:MoveTo(layout:cellCenter(route.cells[route.index[here] + 1]))
	return true
end

function Monster:pickWanderTarget()
	if self.rng:NextNumber() < SETTINGS.HuntChance then
		local targets = self:targets()
		if #targets > 0 then
			return targets[self.rng:NextInteger(1, #targets)].root.Position
		end
	end
	local maze = self.layout.maze
	return self.layout:cellCenter(self.rng:NextInteger(1, maze.width * maze.height))
end

function Monster:setChasing(chasing)
	if self.chasing ~= chasing then
		self.chasing = chasing
		self.model:SetAttribute("Chasing", chasing)
	end
end

-- Если за 1.5 секунды монстр почти не сдвинулся — сбрасываем маршрут и цель.
function Monster:checkStuck(now)
	if now - self.progressTime < 1.5 then
		return
	end
	local moved = flatDistance(self.root.Position, self.progressPosition)
	self.progressTime = now
	self.progressPosition = self.root.Position
	if moved < 1 then
		self.route = nil
		self.wanderTarget = nil
		self.directBlockedUntil = now + 1.5
	end
end

function Monster:catch(player)
	scare(player, "Monster")
	self.pausedUntil = os.clock() + SETTINGS.PauseAfterKill
	self.lastSeenPosition = nil
	self.route = nil
	self:setChasing(false)
end

function Monster:step()
	local now = os.clock()
	if now < self.pausedUntil then
		self.humanoid:MoveTo(self.root.Position)
		self.progressTime = now
		return
	end
	self:checkStuck(now)

	local player, targetRoot, visible = self:findTarget()
	if player then
		if (targetRoot.Position - self.root.Position).Magnitude <= SETTINGS.CatchRange then
			self:catch(player)
			return
		end
		self:setChasing(true)
		self.lastSeenPosition = targetRoot.Position
		self.lastSeenTime = now
		self.humanoid.WalkSpeed = SETTINGS.ChaseSpeed
		if visible and now >= self.directBlockedUntil then
			self.route = nil
			self.humanoid:MoveTo(targetRoot.Position)
		else
			self:followPathTo(targetRoot.Position)
		end
		return
	end

	-- Потерял из виду: идёт туда, где видел игрока в последний раз.
	if self.lastSeenPosition and now - self.lastSeenTime < SETTINGS.SearchTime then
		if self:followPathTo(self.lastSeenPosition) then
			return
		end
	end
	self.lastSeenPosition = nil
	self:setChasing(false)

	self.humanoid.WalkSpeed = SETTINGS.WanderSpeed
	if not self:followPathTo(self.wanderTarget) then
		self.wanderTarget = self:pickWanderTarget()
	end
end

return Monster
