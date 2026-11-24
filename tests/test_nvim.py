"""Drive sb.lua in a real headless Neovim (skipped if nvim isn't installed)."""

import json
import os
import shutil
import subprocess
import sys

import pytest

from secondbrain.cli import NVIM_LUA, lua_string
from secondbrain.vault import Vault

NVIM = shutil.which("nvim")
pytestmark = pytest.mark.skipif(NVIM is None, reason="nvim not installed")

SCRIPT = r"""
local results = {}
local function find(pattern)
  for _, b in ipairs(vim.api.nvim_list_bufs()) do
    local n = vim.api.nvim_buf_get_name(b)
    if n:match(pattern) then return b, n end
  end
end
-- cursor on the [[Beta]] link in line 2 of Alpha, then gf (the sb mapping)
vim.api.nvim_win_set_cursor(0, { LINE, COL })
vim.cmd("normal gf")
results.after_gf = vim.fn.expand("%:t")
-- markdown link back to Alpha with <CR>
vim.cmd("normal! gg")
vim.fn.search("](")
vim.cmd("execute \"normal \\<CR>\"")
results.after_cr = vim.fn.expand("%:t")
-- backlinks of Alpha: Beta links to it
vim.cmd("SbBacklinks")
results.backlinks = vim.tbl_map(function(i) return vim.fn.fnamemodify(vim.fn.bufname(i.bufnr), ":t") .. ":" .. i.lnum end, vim.fn.getqflist())
vim.cmd("cclose")
-- completion items for "gam"
results.complete = vim.tbl_map(function(i) return i.word end, _G.sb_omnifunc(0, "gam"))
results.mapped = vim.fn.maparg("gb", "n") ~= ""
io.stdout:write(vim.json.encode(results))
vim.cmd("qa!")
"""


def test_sb_lua_follows_links_and_lists_backlinks(machine):
    cfg = machine("n")
    vault = Vault(cfg)
    alpha = vault.create("Alpha", body="\n# Alpha\nsee [[Beta]] here\n")
    beta = vault.create("Beta", body=f"\n# Beta\nback to [alpha]({alpha.path.name})\n")
    vault.create("Gamma ray")

    lines = alpha.path.read_text().splitlines()
    line = next(i for i, l in enumerate(lines, 1) if "[[Beta]]" in l)
    col = lines[line - 1].index("[[Beta]]") + 3
    script = cfg.home / "t.lua"
    script.write_text(SCRIPT.replace("LINE", str(line)).replace("COL", str(col)))

    env = dict(os.environ, SB_PYTHON=sys.executable, SB_NOTES_DIR=str(cfg.notes_dir),
               SB_HOME=str(cfg.home), SB_KEY_FILE=str(cfg.key_file))
    proc = subprocess.run(
        [NVIM, "--headless", "--clean", "-c", f"lua dofile({lua_string(str(NVIM_LUA))})",
         "-c", f"luafile {script}", str(alpha.path)],
        env=env, capture_output=True, text=True, timeout=60,
    )
    results = json.loads(proc.stdout or proc.stderr or "{}")
    assert results["after_gf"] == beta.path.name
    assert results["after_cr"] == alpha.path.name
    beta_line = next(i for i, l in enumerate(beta.path.read_text().splitlines(), 1) if "](" in l)
    assert results["backlinks"] == [f"{beta.path.name}:{beta_line}"]
    assert results["complete"] == ["Gamma ray"]
    assert results["mapped"]
