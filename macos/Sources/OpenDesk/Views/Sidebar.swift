import SwiftUI

struct Sidebar: View {
    @Binding var selection: AppSection?
    @EnvironmentObject var permissions: PermissionsService
    @EnvironmentObject var settings:    SettingsStore

    var body: some View {
        VStack(spacing: 0) {
            brandHeader

            ScrollView {
                VStack(spacing: 2) {
                    Group {
                        sectionLabel("Workspace")
                        item(.local)
                        item(.overview)
                        item(.chat)
                        item(.tools)
                    }
                    Group {
                        sectionLabel("Automate")
                        item(.workflows)
                        item(.schedules)
                    }
                    Group {
                        sectionLabel("Network")
                        item(.peers)
                    }
                    Group {
                        sectionLabel("System")
                        item(.audit)
                        item(.settings)
                    }
                }
                .padding(.horizontal, 10)
                .padding(.vertical, 12)
            }

            Spacer(minLength: 0)
            statusFooter
        }
        .background(.regularMaterial)
    }

    private var brandHeader: some View {
        HStack(spacing: 11) {
            ZStack {
                RoundedRectangle(cornerRadius: 9, style: .continuous)
                    .fill(Theme.brandGradient)
                    .frame(width: 34, height: 34)
                    .shadow(color: Theme.brandStart.opacity(0.35), radius: 8, y: 3)
                Image(systemName: "command")
                    .font(.system(size: 16, weight: .bold))
                    .foregroundStyle(.white)
            }
            VStack(alignment: .leading, spacing: 1) {
                Text("OpenDesk").font(.system(size: 15, weight: .bold, design: .rounded))
                Text("v0.2.0").font(.system(size: 11)).foregroundStyle(.secondary)
            }
            Spacer()
        }
        .padding(.horizontal, 16)
        .padding(.top, 18)
        .padding(.bottom, 6)
    }

    private func sectionLabel(_ text: String) -> some View {
        Text(text.uppercased())
            .font(.system(size: 10, weight: .semibold))
            .tracking(0.8)
            .foregroundStyle(.secondary)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 10)
            .padding(.top, 10)
            .padding(.bottom, 4)
    }

    private func item(_ section: AppSection) -> some View {
        SidebarItem(section: section, isSelected: selection == section) {
            selection = section
        }
    }

    private var statusFooter: some View {
        VStack(spacing: 8) {
            Divider().opacity(0.4)
            HStack(spacing: 8) {
                Circle()
                    .fill(permissions.allGranted ? Theme.mint : Theme.amber)
                    .frame(width: 8, height: 8)
                    .shadow(color: permissions.allGranted ? Theme.mint : Theme.amber, radius: 4)
                Text(permissions.allGranted ? "Permissions OK" : "Permissions needed")
                    .font(.system(size: 11, weight: .medium))
                Spacer()
                Button {
                    selection = .settings
                } label: {
                    Image(systemName: "arrow.right.circle.fill")
                        .font(.system(size: 12))
                }
                .buttonStyle(.plain)
                .foregroundStyle(.secondary)
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 10)
        }
    }
}

struct SidebarItem: View {
    let section: AppSection
    let isSelected: Bool
    let action: () -> Void

    @State private var hovering = false

    var body: some View {
        Button(action: action) {
            HStack(spacing: 11) {
                ZStack {
                    RoundedRectangle(cornerRadius: 6, style: .continuous)
                        .fill(isSelected ? section.tint.opacity(0.18) : Color.primary.opacity(0.05))
                        .frame(width: 24, height: 24)
                    Image(systemName: section.systemImage)
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(isSelected ? section.tint : .secondary)
                }
                Text(section.title)
                    .font(.system(size: 13, weight: isSelected ? .semibold : .medium))
                    .foregroundStyle(isSelected ? .primary : .secondary)
                Spacer()
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 7)
            .background {
                RoundedRectangle(cornerRadius: 9, style: .continuous)
                    .fill(isSelected
                          ? Color.primary.opacity(0.07)
                          : (hovering ? Color.primary.opacity(0.04) : .clear))
            }
            .overlay(alignment: .leading) {
                if isSelected {
                    RoundedRectangle(cornerRadius: 2)
                        .fill(section.tint)
                        .frame(width: 3, height: 18)
                        .offset(x: -4)
                        .transition(.opacity)
                }
            }
        }
        .buttonStyle(.plain)
        .onHover { hovering = $0 }
        .animation(.easeOut(duration: 0.12), value: isSelected)
        .animation(.easeOut(duration: 0.12), value: hovering)
    }
}
