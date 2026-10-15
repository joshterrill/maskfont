# maskfont

Generate a font whose glyphs **display** one string while the underlying, text stays **something else**.

- Displayed text = `--input` (what you see)
- Copied text = `--output` (what it actually says)
- Requirement: `len(input) >= len(output)`

## Usage

```sh
python3 maskfont.py --input "kitten" --output "cat" --name "Masked" --outdir out
```

Setup:

```sh
python3 -m venv .venv && ./.venv/bin/pip install fonttools uharfbuzz brotli pytest
./.venv/bin/python -m pytest
```

## License

MIT