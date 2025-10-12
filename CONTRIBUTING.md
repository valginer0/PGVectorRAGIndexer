# Contributing to PGVectorRAGIndexer

Thank you for your interest in contributing to PGVectorRAGIndexer! 🎉

We welcome contributions from the community to help make this project better.

## 📜 License Agreement

This project uses a **Community License** that allows:
- ✅ Forking for personal use and development
- ✅ Submitting bug reports and feature requests
- ✅ Proposing improvements and enhancements
- ✅ Contributing code via pull requests

By contributing to this project, you agree that your contributions will be licensed under the same Community License terms as the project.

## 🚀 How to Contribute

### Reporting Bugs

If you find a bug, please create an issue with:
- **Clear description** of the problem
- **Steps to reproduce** the issue
- **Expected behavior** vs actual behavior
- **Environment details** (OS, Python version, etc.)
- **Error messages** or logs if applicable

### Suggesting Features

We love new ideas! To suggest a feature:
- **Check existing issues** to avoid duplicates
- **Describe the feature** and its use case
- **Explain why** it would be valuable
- **Provide examples** if possible

### Contributing Code

1. **Fork the repository**
   ```bash
   git clone https://github.com/valginer0/PGVectorRAGIndexer.git
   cd PGVectorRAGIndexer
   ```

2. **Create a feature branch**
   ```bash
   git checkout -b feature/your-feature-name
   ```

3. **Set up development environment**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

4. **Make your changes**
   - Follow existing code style
   - Add type hints
   - Include docstrings
   - Write tests for new features

5. **Run tests**
   ```bash
   # Run all tests
   pytest -v
   
   # Run with coverage
   pytest --cov=. --cov-report=term
   ```

6. **Commit your changes**
   ```bash
   git add .
   git commit -m "feat: Add your feature description"
   ```
   
   Use conventional commit messages:
   - `feat:` - New feature
   - `fix:` - Bug fix
   - `docs:` - Documentation changes
   - `test:` - Test additions/changes
   - `refactor:` - Code refactoring
   - `chore:` - Maintenance tasks

7. **Push to your fork**
   ```bash
   git push origin feature/your-feature-name
   ```

8. **Create a Pull Request**
   - Go to the original repository
   - Click "New Pull Request"
   - Select your branch
   - Provide a clear description of changes
   - Reference any related issues

## 🧪 Testing Guidelines

- **Write tests** for all new features
- **Maintain coverage** above 80%
- **Test edge cases** and error conditions
- **Use fixtures** for common test data
- **Mock external dependencies** (database, APIs)

Example test structure:
```python
def test_feature_name():
    """Test description."""
    # Arrange
    input_data = "test"
    
    # Act
    result = function_under_test(input_data)
    
    # Assert
    assert result == expected_value
```

## 📝 Code Style

- **Follow PEP 8** Python style guide
- **Use type hints** for all functions
- **Write docstrings** for modules, classes, and functions
- **Keep functions focused** - single responsibility
- **Use meaningful names** for variables and functions
- **Add comments** for complex logic

Example:
```python
def process_document(file_path: str, chunk_size: int = 500) -> List[str]:
    """
    Process a document into chunks.
    
    Args:
        file_path: Path to the document file
        chunk_size: Maximum size of each chunk
        
    Returns:
        List of text chunks
        
    Raises:
        FileNotFoundError: If file doesn't exist
    """
    # Implementation
    pass
```

## 🔍 Code Review Process

All contributions go through code review:
- **Automated checks** must pass (tests, linting)
- **Code review** by maintainers
- **Feedback** may be provided for improvements
- **Approval** required before merging

## 🎯 Priority Areas

We especially welcome contributions in:
- 🐛 **Bug fixes** - Help make the system more stable
- 📚 **Documentation** - Improve guides and examples
- 🧪 **Tests** - Increase coverage and reliability
- 🚀 **Performance** - Optimize slow operations
- 🔌 **Integrations** - Add support for new formats/services
- 🌐 **Internationalization** - Multi-language support

## ❓ Questions?

- **Check documentation** - README_v2.md, DEPLOYMENT.md, etc.
- **Search issues** - Your question may already be answered
- **Create an issue** - For questions not covered elsewhere
- **Contact maintainer** - valginer0@gmail.com for complex inquiries

## 🙏 Recognition

Contributors will be:
- **Listed** in project documentation
- **Credited** in release notes
- **Appreciated** by the community! ❤️

## 📋 Pull Request Checklist

Before submitting, ensure:
- [ ] Code follows project style guidelines
- [ ] All tests pass locally
- [ ] New tests added for new features
- [ ] Documentation updated if needed
- [ ] Commit messages are clear and descriptive
- [ ] No merge conflicts with main branch
- [ ] Changes are focused and atomic

## 🚫 What We Don't Accept

- Code without tests
- Breaking changes without discussion
- Plagiarized or unlicensed code
- Changes that violate the license terms
- Malicious or harmful code

## 💡 Tips for Success

1. **Start small** - Fix a typo, improve docs, add a test
2. **Communicate early** - Discuss big changes before implementing
3. **Be patient** - Reviews take time
4. **Be respectful** - Follow code of conduct
5. **Have fun!** - Enjoy contributing! 🎉

---

**Thank you for contributing to PGVectorRAGIndexer!** 🚀

Your contributions help make semantic search accessible to everyone.
