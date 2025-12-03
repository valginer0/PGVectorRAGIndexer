# Skill: Create Detailed Code Explanation

## Skill Name
**Detailed Code Explanation Generator**

## Skill Description
Generate comprehensive architectural explanations of code changes in pull requests. This skill produces developer-focused technical documentation that describes WHAT implementation changes were made and HOW different components work together, without requiring access to the actual line-by-line diff.

## Input Parameters

### Required Parameters
1. **PROJECT_NAME** (string)
   - The name of the project/repository
   - Example: "Black (psf/black)", "Django", "React", "Linux Kernel"
   - Format: "ProjectName" or "Organization/Repository"

2. **PR_NUMBER** (string/integer)
   - The pull request or merge request number
   - Example: "3822", "#3822", "MR-456"

3. **FEATURE_NAME** (string)
   - Brief description of what the PR implements
   - Example: "PEP 701 support for f-strings", "async authentication", "WebGPU renderer"

### Optional Parameters
4. **PR_URL** (string, optional)
   - Direct URL to the pull request
   - Helps with fetching additional context if available
   - Example: "https://github.com/psf/black/pull/3822"

5. **FOCUS_AREAS** (list, optional)
   - Specific modules or aspects to emphasize
   - Example: ["tokenizer", "parser", "AST changes"]

6. **AUDIENCE_LEVEL** (enum, optional)
   - Target audience: "maintainer", "contributor", "researcher", "general"
   - Default: "contributor"

7. **INCLUDE_TESTS** (boolean, optional)
   - Whether to include test file explanations
   - Default: false

## Output Format

The skill generates a structured markdown document containing:

### Document Structure
1. **Title**: "Detailed Explanation of [FEATURE_NAME] Implementation in [PROJECT_NAME] PR #[NUMBER]"

2. **Overview Section**
   - High-level summary of changes
   - Purpose and motivation
   - Architectural approach

3. **Component-by-Component Analysis**
   For each modified file/module:
   - Module purpose and role
   - New functionality added
   - Implementation details (algorithms, data structures, state management)
   - New functions/methods and their purposes
   - Component interactions
   - Helper functions

4. **Integration Points**
   - How changes across modules work together
   - Data flow between components
   - Call sequences and control flow

5. **Edge Cases**
   - Special cases handled
   - Error conditions
   - Boundary conditions

6. **Backwards Compatibility**
   - Compatibility implications
   - Migration considerations
   - Deprecation notes

7. **Performance Considerations**
   - Performance impacts
   - Optimizations applied
   - Complexity analysis

8. **Future Work**
   - Capabilities enabled
   - Planned enhancements
   - Extension points

9. **Summary**
   - Changes by file with estimated line counts
   - Key architectural decisions
   - Overall impact

### Technical Detail Guidelines
- **Algorithms**: Step-by-step numbered explanations
- **Code concepts**: Pseudo-code or conceptual code snippets
- **Data structures**: Purpose, organization, and usage patterns
- **State management**: Variables tracked, state transitions
- **Recursive logic**: Base cases and recursive cases clearly explained
- **Interactions**: Call graphs, data flow diagrams (textual)

## Execution Process

### Step 1: Information Gathering
```
When given parameters:
- Attempt to fetch PR information from provided URL if available
- Search for PR details using PROJECT_NAME and PR_NUMBER
- Gather context about the feature from available sources
- Identify key files changed (if accessible)
```

### Step 2: Analysis
```
Analyze the PR to identify:
- Primary code changes (non-test files)
- Modified modules and their purposes
- New abstractions or patterns introduced
- Integration points between modules
- Design decisions and tradeoffs
```

### Step 3: Documentation Generation
```
Generate explanation following the output format:
- Start with clear overview
- Explain each major module's changes
- Detail algorithms and data structures
- Cover edge cases and compatibility
- Summarize with file-level breakdown
```

### Step 4: Quality Validation
```
Ensure the explanation:
- Is detailed enough to understand architecture without seeing code
- Uses consistent technical terminology
- Includes concrete examples
- Explains the "why" behind design decisions
- Is structured for easy navigation
```

## Usage Examples

### Example 1: Basic Usage
```
Input Parameters:
- PROJECT_NAME: "Black (psf/black)"
- PR_NUMBER: "3822"
- FEATURE_NAME: "PEP 701 support for f-strings"

Output: [Full architectural explanation document as previously generated]
```

### Example 2: With Focus Areas
```
Input Parameters:
- PROJECT_NAME: "React"
- PR_NUMBER: "18299"
- FEATURE_NAME: "Concurrent rendering"
- FOCUS_AREAS: ["scheduler", "reconciler", "fiber architecture"]

Output: [Explanation emphasizing scheduler, reconciler, and fiber changes]
```

### Example 3: For Researchers
```
Input Parameters:
- PROJECT_NAME: "TensorFlow"
- PR_NUMBER: "45678"
- FEATURE_NAME: "XLA compiler optimizations"
- AUDIENCE_LEVEL: "researcher"

Output: [More theoretical explanation including complexity analysis and algorithmic details]
```

## Skill Invocation Format

### Command Line Style
```bash
explain-pr --project "Black (psf/black)" \
           --pr 3822 \
           --feature "PEP 701 support for f-strings" \
           --output explanation.md
```

### Natural Language Style
```
Please create a detailed code explanation for:
- Project: Black (psf/black)
- Pull Request: #3822
- Feature: PEP 701 support for f-strings
```

### Structured Format
```json
{
  "skill": "detailed_code_explanation",
  "parameters": {
    "project_name": "Black (psf/black)",
    "pr_number": "3822",
    "feature_name": "PEP 701 support for f-strings",
    "pr_url": "https://github.com/psf/black/pull/3822",
    "include_tests": false,
    "audience_level": "contributor"
  }
}
```

## Quality Criteria

A successful explanation must:

### Completeness
- [ ] Covers all major code modules affected
- [ ] Explains new abstractions introduced
- [ ] Details integration between components
- [ ] Addresses edge cases and special handling

### Clarity
- [ ] Uses consistent terminology
- [ ] Provides concrete examples
- [ ] Explains complex concepts step-by-step
- [ ] Includes visual/structural descriptions

### Technical Depth
- [ ] Details algorithms and data structures
- [ ] Explains state management
- [ ] Covers performance implications
- [ ] Describes design patterns used

### Actionability
- [ ] Developer could understand architectural approach
- [ ] Clear enough to guide similar implementations
- [ ] Identifies extension points
- [ ] Notes future work opportunities

### Accuracy
- [ ] Reflects actual changes made
- [ ] Correctly describes component interactions
- [ ] Accurately represents design decisions
- [ ] No speculation presented as fact

## Limitations and Disclaimers

### What This Skill Provides
✅ Architectural understanding of code changes
✅ Component-level implementation details
✅ Design decisions and tradeoffs
✅ Integration and interaction patterns

### What This Skill Does NOT Provide
❌ Line-by-line code diff
❌ Complete source code reproduction
❌ Syntax-level implementation details
❌ Guarantee of 100% accuracy without code access

### Best Used When
- Understanding architectural changes
- Planning similar implementations
- Reviewing design decisions
- Learning from established projects
- Creating technical documentation

### May Have Limitations When
- PR is extremely large (>5000 lines)
- Changes are primarily cosmetic (formatting, renaming)
- Actual code diff is not accessible
- Project uses non-standard architecture

## Skill Metadata

- **Version**: 1.0
- **Category**: Software Engineering / Code Analysis
- **Complexity**: Advanced
- **Estimated Output Length**: 2000-5000 words
- **Execution Time**: 2-5 minutes
- **Dependencies**: Web search access (optional), PR URL access (optional)
- **Output Format**: Markdown document
- **Language**: English (default)

## Skill Improvement Suggestions

### For Future Versions
1. Support for comparing multiple related PRs
2. Automatic diagram generation (ASCII art architecture diagrams)
3. Language-specific analysis (Python vs Rust vs JavaScript)
4. Integration with code analysis tools
5. Support for generating from commit ranges
6. Template customization options
7. Multi-language output support

## Related Skills

- **Code Review Generator**: Creates review comments for PRs
- **API Documentation Generator**: Generates API docs from code
- **Refactoring Guide Creator**: Documents refactoring patterns
- **Test Strategy Explainer**: Explains test coverage approach
- **Migration Guide Writer**: Creates migration documentation

## Skill Usage Tips

### For Best Results
1. Provide PR URL when possible for better context
2. Specify focus areas if the PR is very large
3. Indicate audience level for appropriate depth
4. Use for architectural understanding, not syntax details
5. Review and validate technical accuracy

### Common Use Cases
- Onboarding new team members
- Creating technical documentation
- Understanding complex features
- Learning architectural patterns
- Preparing conference talks
- Writing blog posts about implementations

## Licensing and Attribution

When using explanations generated by this skill:
- Attribute to the original PR authors and project
- Link back to the original PR
- Note that this is an architectural interpretation
- Verify critical technical details when possible
- Follow the project's documentation license

---

**Skill ID**: `detailed-code-explanation-v1`  
**Last Updated**: 2024  
**Maintainer**: Documentation Team  
**Status**: Active
