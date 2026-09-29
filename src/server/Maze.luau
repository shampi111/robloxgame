-- Генерация лабиринта на сетке и поиск путей. Только данные, без деталей:
-- клетки пронумерованы от 1 до width * height построчно, links[a][b] = true,
-- если между соседними клетками a и b нет стены.
local Maze = {}
Maze.__index = Maze

function Maze.new(width, height)
	local self = setmetatable({ width = width, height = height, links = {} }, Maze)
	for i = 1, width * height do
		self.links[i] = {}
	end
	return self
end

-- x от 0 до width - 1, y от 0 до height - 1
function Maze:index(x, y)
	return y * self.width + x + 1
end

function Maze:coords(i)
	local zeroBased = i - 1
	return zeroBased % self.width, zeroBased // self.width
end

-- Соседи по сетке, без учёта стен.
function Maze:gridNeighbors(i)
	local x, y = self:coords(i)
	local result = {}
	if x > 0 then
		table.insert(result, i - 1)
	end
	if x < self.width - 1 then
		table.insert(result, i + 1)
	end
	if y > 0 then
		table.insert(result, i - self.width)
	end
	if y < self.height - 1 then
		table.insert(result, i + self.width)
	end
	return result
end

function Maze:link(a, b)
	self.links[a][b] = true
	self.links[b][a] = true
end

function Maze:isLinked(a, b)
	return self.links[a][b] == true
end

-- Соседи, в которые можно пройти.
function Maze:exits(i)
	local result = {}
	for neighbor in self.links[i] do
		table.insert(result, neighbor)
	end
	table.sort(result)
	return result
end

-- Лабиринт методом «рекурсивного возврата» (все клетки связаны),
-- плюс немного лишних проходов, чтобы появились петли и от монстра можно было убежать.
-- rng — объект Random (нужны NextInteger и NextNumber).
function Maze.generate(width, height, rng, extraOpenings)
	local maze = Maze.new(width, height)
	local visited = { [1] = true }
	local stack = { 1 }
	while #stack > 0 do
		local current = stack[#stack]
		local candidates = {}
		for _, neighbor in maze:gridNeighbors(current) do
			if not visited[neighbor] then
				table.insert(candidates, neighbor)
			end
		end
		if #candidates > 0 then
			local nextCell = candidates[rng:NextInteger(1, #candidates)]
			maze:link(current, nextCell)
			visited[nextCell] = true
			table.insert(stack, nextCell)
		else
			table.remove(stack)
		end
	end

	for i = 1, width * height do
		local x, y = maze:coords(i)
		if x < width - 1 and not maze:isLinked(i, i + 1) and rng:NextNumber() < extraOpenings then
			maze:link(i, i + 1)
		end
		if y < height - 1 and not maze:isLinked(i, i + width) and rng:NextNumber() < extraOpenings then
			maze:link(i, i + width)
		end
	end
	return maze
end

-- Расстояния в клетках от from до всех клеток (поиск в ширину).
function Maze:distances(from)
	local distances = { [from] = 0 }
	local queue, head = { from }, 1
	while head <= #queue do
		local current = queue[head]
		head += 1
		for _, neighbor in self:exits(current) do
			if distances[neighbor] == nil then
				distances[neighbor] = distances[current] + 1
				table.insert(queue, neighbor)
			end
		end
	end
	return distances
end

-- Кратчайший путь: список клеток от from до to включительно, или nil.
function Maze:path(from, to)
	local previous = { [from] = from }
	local queue, head = { from }, 1
	while head <= #queue do
		local current = queue[head]
		head += 1
		if current == to then
			local path = { to }
			while path[1] ~= from do
				table.insert(path, 1, previous[path[1]])
			end
			return path
		end
		for _, neighbor in self:exits(current) do
			if previous[neighbor] == nil then
				previous[neighbor] = current
				table.insert(queue, neighbor)
			end
		end
	end
	return nil
end

-- Тупики: клетки с единственным проходом.
function Maze:deadEnds()
	local result = {}
	for i = 1, self.width * self.height do
		if #self:exits(i) == 1 then
			table.insert(result, i)
		end
	end
	return result
end

return Maze
