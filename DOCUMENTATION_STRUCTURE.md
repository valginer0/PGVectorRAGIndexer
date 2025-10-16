# Documentation Structure

This document explains the purpose of each documentation file and when to use them.

## 📚 User Documentation

### For End Users (Docker-Only Deployment)

| Document | Purpose | Audience |
|----------|---------|----------|
| **[README.md](README.md)** | Main entry point, project overview, quick start | Everyone |
| **[QUICK_START.md](QUICK_START.md)** | 5-minute setup for Linux/macOS/WSL | Linux/macOS/WSL users |
| **[WINDOWS_SETUP.md](WINDOWS_SETUP.md)** | Detailed Windows native setup | Windows users (no WSL) |
| **[DEPLOYMENT_OPTIONS.md](DEPLOYMENT_OPTIONS.md)** | Compare all deployment methods | Users choosing deployment method |
| **[USAGE_GUIDE.md](USAGE_GUIDE.md)** | Detailed API usage and examples | All users after installation |

### For Advanced Users

| Document | Purpose | Audience |
|----------|---------|----------|
| **[DEPLOYMENT.md](DEPLOYMENT.md)** | Production deployment (systemd, nginx, cloud) | DevOps, production deployments |
| **[BACKUP_GUIDE.md](BACKUP_GUIDE.md)** | Database backup and recovery | System administrators |
| **[TESTING_GUIDE.md](TESTING_GUIDE.md)** | Running tests, test structure | Developers, QA |

## 🔧 Developer Documentation

| Document | Purpose | Audience |
|----------|---------|----------|
| **[CONTRIBUTING.md](CONTRIBUTING.md)** | Contribution guidelines | Contributors |
| **[CHANGELOG.md](CHANGELOG.md)** | Version history and changes | Everyone |
| **[RELEASE_INSTRUCTIONS.md](RELEASE_INSTRUCTIONS.md)** | How to create releases | Maintainers |

## 🗺️ Documentation Flow

### New User Journey

```
1. README.md (overview)
   ↓
2. Choose platform:
   - Windows → WINDOWS_SETUP.md
   - Linux/macOS/WSL → QUICK_START.md
   - Comparing options → DEPLOYMENT_OPTIONS.md
   ↓
3. USAGE_GUIDE.md (learn API)
   ↓
4. Advanced: DEPLOYMENT.md (production)
```

### Developer Journey

```
1. README.md (overview)
   ↓
2. CONTRIBUTING.md (guidelines)
   ↓
3. TESTING_GUIDE.md (run tests)
   ↓
4. RELEASE_INSTRUCTIONS.md (create release)
```

## 📋 Quick Reference

### "I want to..."

- **"...get started quickly on Windows"** → [WINDOWS_SETUP.md](WINDOWS_SETUP.md)
- **"...get started quickly on Linux/macOS"** → [QUICK_START.md](QUICK_START.md)
- **"...compare deployment options"** → [DEPLOYMENT_OPTIONS.md](DEPLOYMENT_OPTIONS.md)
- **"...learn the API"** → [USAGE_GUIDE.md](USAGE_GUIDE.md)
- **"...deploy to production"** → [DEPLOYMENT.md](DEPLOYMENT.md)
- **"...backup my data"** → [BACKUP_GUIDE.md](BACKUP_GUIDE.md)
- **"...run tests"** → [TESTING_GUIDE.md](TESTING_GUIDE.md)
- **"...see what changed"** → [CHANGELOG.md](CHANGELOG.md)

## 🎯 Key Features Documented

All documentation now consistently covers:

### ✅ Multi-Platform Support
- **Windows native** (PowerShell, no WSL required)
- **Linux/macOS/WSL** (Bash scripts)
- **Docker Desktop** or **Rancher Desktop**

### ✅ File Upload Feature
- Upload from **any Windows directory** (C:, D:, network drives)
- Upload from **any Linux/macOS directory**
- No need to copy files to Docker mount point

### ✅ Docker-Only Deployment
- Single command installation
- No Python installation needed
- No repository clone needed
- Pre-built images from GitHub Container Registry

## 📝 Maintenance Notes

### When to Update Documentation

1. **New Feature** → Update USAGE_GUIDE.md, CHANGELOG.md, README.md
2. **Bug Fix** → Update CHANGELOG.md
3. **Deployment Change** → Update relevant deployment guide
4. **API Change** → Update USAGE_GUIDE.md, README.md examples
5. **New Release** → Update CHANGELOG.md, VERSION file

### Documentation Standards

- Use **clear headings** with emoji for visual scanning
- Include **code examples** for all features
- Provide **both Windows and Linux** examples where applicable
- Keep **CHANGELOG.md** up to date with every release
- Cross-reference related documents

## 🗑️ Removed Documentation

The following files were removed as obsolete:

- `README_v1_legacy.md` - Old v1 documentation (superseded by v2)
- `IMPROVEMENTS_SUMMARY.md` - One-time migration document
- `LICENSING_SUMMARY.md` - Redundant (info in LICENSE files)
- `OWNERSHIP_NOTES.md` - Internal development notes

## 📊 Documentation Metrics

- **Total documentation files**: 11
- **User-facing docs**: 5
- **Developer docs**: 3
- **Advanced/production docs**: 3
- **Lines removed**: ~1,100 (obsolete docs)
- **Platforms supported**: Windows, Linux, macOS, WSL

---

**Last Updated**: 2025-10-16  
**Version**: 2.0.2+
