# Building Dev-Jesus: A Journey Through AI-Assisted Narrative Generation

This article traces the development of a pipeline for generating AI-assisted comic book narratives, from initial concept through the bugs and features that proved essential for visual and narrative continuity.

## The Genesis: Initial Commit (January 14, 2026)

The project began with three core scripts designed to work together as a pipeline:

1. **generate_scenes.py** - Transform act structures into prose scenes
2. **generate_storyboards.py** - Convert scenes into visual comic panels  
3. **generate_narrative.py** - Interactive scaffolding based on Borges' Four Cycles

### The Original Vision

The initial implementation was surprisingly simple. The scene generator started with a hardcoded premise:

```python
core_premise = "Human reality is a simulation. Jesus is a systems engineer from the originating civilization who entered as a constrained instance to deliver a corrective signal."
```

The prompt was direct: generate a scene in third person, past tense, with 2-3 sections marked by `##` headings. The key constraint? *"Maintain the tone: avoid reverence, avoid mockery, treat humanity as understandable."*

The storyboard generator detected characters and settings by simple string matching against a definitions file, then fed everything into Gemini's image generation with instructions for "biblical-meets-sci-fi" aesthetics.

### Borges as Framework

The narrative scaffolding script drew from Jorge Luis Borges' essay "Los Cuatro Ciclos" (The Four Cycles), structuring stories around four archetypal patterns:

1. **The Troy Cycle** - War, destruction, rebuilding
2. **The Search Cycle** - Quest, journey, discovery  
3. **The Return Cycle** - Homecoming, recognition, restoration
4. **The Sacrifice Cycle** - Ritual, transformation, transcendence

This wasn't just a literary flourish—it provided a genuine structural backbone for procedurally generated narratives, ensuring each act had thematic coherence.

## First Bug Fix: File Naming (January 14, 2026)

The very first fix after launch was mundane but critical:

```diff
-output_path = os.path.join(args.output_dir, f"scene-{scene_num}.md")
+output_path = os.path.join(args.output_dir, f"scene-{scene_num:04d}.md")
```

Zero-padding scene numbers (0001 instead of 1) ensured proper sort order. This small change affected the entire pipeline—storyboards needed consistent naming to match their source scenes.

## The Continuity Crisis (January 15, 2026)

The "Updates" commit on January 15th represents a watershed moment. The generated scenes were working, but they had a fundamental problem: **no memory**.

### The Problem

Each scene was generated in isolation. The LLM had no awareness of what happened before. Characters would change vehicles mid-story. Objects would appear and disappear. Emotional states would reset between scenes.

### The Solution: Continuity Notes

I introduced `extract_continuity_notes()`, which uses the LLM to analyze previous scenes and extract:

- Vehicles/transportation (make, model, color, condition)
- Current location and destination
- Objects characters possess
- Character physical/emotional states
- Plot developments
- Time of day

These notes are cached to `.continuity.md` files, avoiding redundant API calls:

```python
continuity_cache_path = os.path.join(output_dir, f"scene-{scene_num:04d}.continuity.md")
```

The prompt builder now includes these notes:

```python
if continuity_notes:
    previous_context = f"\n\nContinuity from previous scenes (maintain consistency with these details):\n\n{continuity_notes}\n"
```

### Character Definitions

The same commit introduced character and setting definitions from JSON files. Instead of the LLM inventing new characters each time, it now receives explicit definitions:

```python
character_context = "\n\nAvailable Characters (use these consistently in your scenes):\n"
for char_key, char_data in characters.items():
    char_context = f"- {char_data.get('name', char_key)}"
    if "aliases" in char_data:
        char_context += f" (also known as: {', '.join(char_data['aliases'])})"
```

## Visual Reference System (January 15, 2026 - "Updates" commit)

The storyboard generator evolved significantly. The initial version just detected entities in text. The updated version introduced a full reference image system:

### The Reference Image Pipeline

1. **Character References** (`character_references.json`) - Maps character names to image paths
2. **Extra References** (`extra_references.json`) - For non-character entities (vehicles, props)
3. **Setting References** (`setting_references.json`) - Indoor/outdoor views of locations
4. **Style Reference** (`ref-style.jpg`) - Master style guide for the entire comic

When a character appears for the first time, the system generates a canonical reference image:

```python
def generate_character_reference_image(...):
    """Generate a single-panel reference image for a character."""
    prompt = build_character_reference_prompt(character, definitions)
    # ... generates and stores ref-{character-name}.jpg
```

Future storyboards include these reference images directly in the API call, ensuring visual consistency:

```python
if reference_images:
    for img_path in reference_images:
        mime_type, base64_data = load_image_as_base64(img_path)
        parts.append({
            "inlineData": {
                "mimeType": mime_type,
                "data": base64_data,
            }
        })
```

## Dialog-Aware Chunking (January 15, 2026)

The storyboard generation commit brought several improvements:

1. **Better entity detection** - Only include *visually present* characters
2. **Dialog-aware chunking** - Prioritize dialog when deriving panel instructions
3. **Chunk regeneration** - The `--chunks` argument allows regenerating specific storyboard chunks without redoing the whole scene
4. **Increased density** - Default storyboards per scene went from 3-5 to 4-6, panels per storyboard from 3-5 to 4-6

The commit message captures the intent:
> *"Improved panel instructions to explicitly mention detected characters by name"*

## The Era Problem (January 18, 2026)

The "Add alpha/beta stories" commit addressed a subtle but critical bug in multi-era stories.

### The Bug

Consider a story with both biblical-era scenes and present-day scenes. Without era filtering, a biblical laborer might appear in a modern office, or a present-day executive in first-century Galilee.

### The Solution: Era Filtering

Settings and characters now have `era` fields. Scene generation filters both:

```python
# Get the eras from the settings mentioned in this scene
scene_eras = get_eras_from_settings(settings_from_purpose)

# Filter characters by era to match the scene's settings
if scene_eras:
    era_filtered_characters = filter_characters_by_era(all_characters, scene_eras)
```

The prompt now includes explicit era warnings:

```python
if scene_eras:
    character_context += f"\nNOTE: Only characters from era(s): {', '.join(scene_eras)} are shown above. Do NOT use characters from other eras in this scene.\n"
```

### Name Uniqueness

The same commit tackled a creative problem: LLMs default to clichéd names. The definitions generator now explicitly avoids:

> *"Elias, Thorne, Henderson, Marcus, Elena, Clara, James, John, Michael, Sarah, Elizabeth... Generic surnames like Smith, Jones, Miller..."*

And suggests alternatives:
> *"Unusual but real names from diverse cultures (Yoruba, Georgian, Basque, Welsh, Finnish, etc.)"*

## Temperature and Creativity (January 18, 2026)

A subtle but impactful change: bumping the temperature from 0.8 to 1.0 for both scene and narrative generation:

```diff
-"temperature": 0.8,
+"temperature": 1.0,
```

Higher temperature means more creative variation—essential for generating distinctive character names and avoiding repetitive phrasing.

## Project Reorganization (January 19, 2026)

An early change moved all stories into a `stories/` subdirectory:

```diff
-story_path = os.path.join(script_root, story_dir)
+story_path = os.path.join(script_root, "stories", story_dir)
```

And introduced a proper directory structure:
- `stories/{name}/` - Root story directory
- `stories/{name}/scenes/` - Generated scene markdown files
- `stories/{name}/boards/` - Generated storyboard images
- `stories/{name}/boards/refs/` - Reference images

## Non-Linear Extras Introduction (January 19, 2026)

A subtle but story-breaking bug emerged when testing the "pancake" story: **extras appearing before their narrative introduction**.

### The Problem

Consider a story where a mysterious cigar box is revealed in scene 5 as a key plot element. Without extras filtering, the LLM might mention the cigar box in scene 2 because it's in the definitions file—destroying the narrative surprise.

This is different from character or setting filtering. Characters and settings are filtered by *era* (biblical vs. present-day). But extras (objects, props, MacGuffins) need filtering by *narrative introduction point*—the moment they first appear in the story structure.

### The Solution: Introduction-Aware Extras

The fix scans scene purposes from the `acts.json` to determine when each extra is first mentioned:

```python
def get_introduced_extras(acts_data: dict, current_scene_number: int, all_extras: dict) -> dict:
    """Get extras that have been introduced in previous scenes or the current scene.
    
    Scans scene purposes from scene 1 up to and including current_scene_number to find
    which extras have been mentioned, ensuring extras don't appear before their narrative introduction.
    """
    introduced_extras = {}
    
    for act in acts_data.get("acts", []):
        for scene_def in act.get("scenes", []):
            scene_num = scene_def.get("number", 0)
            if scene_num > current_scene_number:
                break
            
            scene_purpose = scene_def.get("purpose", "")
            extras_in_scene = extract_extras_from_purpose(scene_purpose, all_extras)
            introduced_extras.update(extras_in_scene)
    
    return introduced_extras
```

The prompt now explicitly warns the LLM about extras it shouldn't use:

```python
not_yet_introduced = set(all_extras.keys()) - set(introduced_extras.keys())
if not_yet_introduced:
    not_introduced_names = [all_extras[k].get("name", k) for k in not_yet_introduced]
    extras_context += f"\nIMPORTANT: Do NOT mention or use these extras yet (they will be introduced in later scenes): {', '.join(not_introduced_names)}\n"
```

### Name Matching Flexibility

The implementation handles common naming patterns—"The Cigar Box" matches "cigar box" in scene purposes by stripping the "The " prefix. This prevents brittle matching while maintaining accuracy.

## Key Lessons Learned

### 1. Continuity is Everything

The single most important feature was continuity notes. Without explicit memory, generative AI produces disconnected content. The investment in extracting and caching continuity information pays off exponentially.

### 2. Reference Images Beat Text Descriptions

For visual generation, showing beats telling. A canonical reference image maintains character appearance far better than the most detailed text description.

### 3. Era Context Prevents Anachronisms

When generating multi-era content, explicit era filtering is essential. The LLM will happily mix eras unless constrained.

### 4. Structure Enables Creativity

The Borges Four Cycles framework isn't limiting—it's enabling. Having a structural backbone lets the LLM focus creativity on the right things: prose style, character voice, sensory detail.

### 5. File Naming Matters

Zero-padded, consistent file naming (`scene-0001.md`) seems trivial until you have 100 scenes and need them in order.

### 6. Narrative Timing is Data

The extras filtering bug revealed an important principle: narrative structure contains temporal information that must be respected. It's not enough to give the LLM all the story elements—you must give them at the right time.

## The Pipeline Today

The current workflow:

1. **`generate_narrative.py`** - Interactive session to establish story concept, characters, settings, and act structure
2. **`generate_scenes.py`** - Converts acts.json into prose scenes, maintaining continuity
3. **`generate_storyboards.py`** - Transforms scenes into visual panels with reference image consistency
4. **`tag_storyboards.py`** - (Added later) Annotates generated images

Each script builds on the others, creating a pipeline from concept to comic.

---

*This development journal was reconstructed from git history spanning January 14-19, 2026. The project continues to evolve as new continuity challenges emerge.*

*Last updated: January 19, 2026 — added non-linear extras introduction filtering.*
