-- sb.lua: link following for sb notes in Neovim (0.10+).
--
-- `sb edit` / `sb new` load this automatically, so no nvim config is needed.
-- To also get it when you open notes with plain `nvim`, see `sb nvim-setup`.
--
-- In a note:
--   gf / <CR>    follow the [[link]] or [text](note.md) under the cursor
--                (offers to create the note if it doesn't exist)
--   gb           backlinks into the quickfix list
--   [[           insert a link with title completion (<C-n>/<C-p>, <C-y>)
--   :SbNew [t]   create a note        :SbLink    pick a note, insert a link
--   :SbBacklinks                      :SbGraph [depth]  graph around this note
--
-- All the logic (how links resolve, what links where) lives in sb's Python;
-- this file only calls `sb _resolve`, `sb _backlinks`, and so on.

if vim.g.loaded_sb then
  return
end
vim.g.loaded_sb = true

local notes_dir = vim.fs.normalize(vim.env.SB_NOTES_DIR or vim.g.sb_notes_dir or "~/.sb/notes")
notes_dir = vim.uv.fs_realpath(notes_dir) or notes_dir
local python = vim.env.SB_PYTHON or vim.g.sb_python

local function sb_cmd(args)
  local cmd = python and { python, "-m", "secondbrain" } or { "sb" }
  return vim.list_extend(cmd, args)
end

--- Run an internal sb command; returns (ok, stdout lines). Exit code 3 means "not found".
local function sb(args)
  local ok_run, proc = pcall(vim.system, sb_cmd(args), { text = true })
  if not ok_run then
    vim.notify("sb: couldn't run sb: " .. tostring(proc), vim.log.levels.ERROR)
    return false, {}
  end
  local res = proc:wait()
  if res.code ~= 0 and res.code ~= 3 then
    vim.notify("sb failed: " .. vim.trim(res.stderr or ""), vim.log.levels.ERROR)
  end
  return res.code == 0, vim.split(vim.trim(res.stdout or ""), "\n", { trimempty = true })
end

local function is_note(buf)
  local name = vim.api.nvim_buf_get_name(buf)
  if name == "" or not name:match("%.md$") then
    return false
  end
  local dir = vim.fs.dirname(name)
  return (vim.uv.fs_realpath(dir) or dir) == notes_dir
end

local function edit(path)
  vim.cmd.edit(vim.fn.fnameescape(path))
end

-- -- links ---------------------------------------------------------------------

--- The link under the cursor: (target, is_markdown_link) or nil.
local function link_under_cursor()
  local line = vim.api.nvim_get_current_line()
  local col = vim.api.nvim_win_get_cursor(0)[2] + 1
  for s, target, e in line:gmatch("()%[%[([^%]|#]+)[^%]]*%]%]()") do
    if col >= s and col < e then
      return vim.trim(target), false
    end
  end
  for s, target, e in line:gmatch("()%[[^%]]*%]%(([^%)%s]+)%)()") do
    if col >= s and col < e then
      return target, true
    end
  end
end

local function create_and_open(title)
  local ok, out = sb({ "_new", title })
  if ok and out[1] then
    edit(out[1])
  end
end

--- Follow the link under the cursor. Returns false if there isn't one.
local function follow()
  local target, is_md = link_under_cursor()
  if not target then
    return false
  end
  if is_md then
    if target:match("^%a[%w+.-]*://") then
      vim.ui.open(target)
      return true
    end
    target = target:gsub("#.*$", "")
    local here = vim.fs.dirname(vim.api.nvim_buf_get_name(0))
    local path = vim.fs.joinpath(here, vim.uri_decode(target))
    if vim.uv.fs_stat(path) then
      edit(path)
      return true
    end
  end
  local ok, out = sb({ "_resolve", target })
  if ok and out[1] then
    edit(out[1])
    return true
  end
  local title = is_md and target:gsub("%.md$", ""):gsub("^.*/", "") or target
  vim.ui.select({ "Create it", "Cancel" }, { prompt = ("No note '%s'."):format(title) }, function(choice)
    if choice == "Create it" then
      create_and_open(title)
    end
  end)
  return true
end

local function backlinks()
  local _, out = sb({ "_backlinks", vim.api.nvim_buf_get_name(0) })
  if #out == 0 then
    vim.notify("sb: no backlinks")
    return
  end
  vim.fn.setqflist({}, " ", { title = "sb backlinks", lines = out, efm = "%f:%l:%c:%m" })
  vim.cmd("botright copen")
end

--- Notes as {title=, tags=, path=}.
local function list_notes()
  local _, out = sb({ "_complete" })
  local notes = {}
  for _, line in ipairs(out) do
    local title, tags, path = line:match("^(.-)\t(.-)\t(.*)$")
    if title then
      table.insert(notes, { title = title, tags = tags, path = path })
    end
  end
  return notes
end

-- -- completion ------------------------------------------------------------------

function _G.sb_omnifunc(findstart, base)
  if findstart == 1 then
    local line = vim.api.nvim_get_current_line()
    local before = line:sub(1, vim.api.nvim_win_get_cursor(0)[2])
    local start = before:match(".*()%[%[")
    if not start or before:sub(start):find("%]%]") then
      return -3 -- not inside [[ ]]: cancel silently
    end
    return start + 1 -- 0-based column just after "[["
  end
  local items, needle = {}, base:lower()
  for _, note in ipairs(list_notes()) do
    if needle == "" or note.title:lower():find(needle, 1, true) then
      table.insert(items, { word = note.title, menu = note.tags, icase = 1 })
    end
  end
  return items
end

-- -- commands ----------------------------------------------------------------------

local function pick_link()
  local notes = list_notes()
  vim.ui.select(notes, {
    prompt = "Link to note",
    format_item = function(n)
      return n.title .. (n.tags ~= "" and ("  " .. n.tags) or "")
    end,
  }, function(note)
    if note then
      vim.api.nvim_put({ "[[" .. note.title .. "]]" }, "c", true, true)
    end
  end)
end

local function graph(depth)
  local stem = vim.fn.expand("%:t:r")
  vim.cmd("tabnew")
  local cmd = sb_cmd({ "-n", "graph", stem, "-d", tostring(depth or 2) })
  if vim.fn.has("nvim-0.11") == 1 then
    vim.fn.jobstart(cmd, { term = true })
  else
    vim.fn.termopen(cmd)
  end
  vim.keymap.set("n", "q", "<cmd>bwipeout!<cr>", { buffer = true, desc = "close graph" })
end

vim.api.nvim_create_user_command("SbNew", function(opts)
  if opts.args ~= "" then
    return create_and_open(opts.args)
  end
  vim.ui.input({ prompt = "New note title: " }, function(title)
    if title and title ~= "" then
      create_and_open(title)
    end
  end)
end, { nargs = "?", desc = "sb: create a note" })
vim.api.nvim_create_user_command("SbLink", pick_link, { desc = "sb: insert a link to a note" })
vim.api.nvim_create_user_command("SbBacklinks", backlinks, { desc = "sb: backlinks to quickfix" })
vim.api.nvim_create_user_command("SbGraph", function(opts)
  graph(tonumber(opts.args))
end, { nargs = "?", desc = "sb: graph around this note" })

-- -- attach to note buffers ------------------------------------------------------

local function attach(buf)
  if vim.b[buf].sb_attached or not is_note(buf) then
    return
  end
  vim.b[buf].sb_attached = true
  vim.bo[buf].omnifunc = "v:lua.sb_omnifunc"
  local map = function(mode, lhs, rhs, desc)
    vim.keymap.set(mode, lhs, rhs, { buffer = buf, desc = "sb: " .. desc })
  end
  map("n", "gf", function()
    if not follow() then
      local ok, err = pcall(vim.cmd, "normal! gf")
      if not ok then
        vim.notify(err:gsub("^Vim:", ""), vim.log.levels.ERROR)
      end
    end
  end, "follow link")
  map("n", "<CR>", function()
    if not follow() then
      vim.api.nvim_feedkeys(vim.keycode("<CR>"), "n", false)
    end
  end, "follow link")
  map("n", "gb", backlinks, "backlinks")
  map("i", "[[", "[[]]<Left><Left><C-x><C-o>", "link with completion")
end

vim.api.nvim_create_autocmd({ "BufRead", "BufNewFile", "BufEnter" }, {
  group = vim.api.nvim_create_augroup("sb", { clear = true }),
  pattern = "*.md",
  callback = function(ev)
    attach(ev.buf)
  end,
})
for _, buf in ipairs(vim.api.nvim_list_bufs()) do
  if vim.api.nvim_buf_is_loaded(buf) then
    attach(buf)
  end
end
