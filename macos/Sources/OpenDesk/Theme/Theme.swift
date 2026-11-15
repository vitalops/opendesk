import SwiftUI

enum Theme {
    // Brand palette — warm indigo → violet with coral accents
    static let brandStart  = Color(red: 0.36, green: 0.28, blue: 0.95)   // #5B47F2
    static let brandEnd    = Color(red: 0.55, green: 0.36, blue: 0.99)   // #8C5BFD
    static let brandSubtle = Color(red: 0.94, green: 0.92, blue: 1.00)   // very light tint
    static let accent      = Color(red: 1.00, green: 0.53, blue: 0.43)   // coral #FF876E
    static let mint        = Color(red: 0.36, green: 0.85, blue: 0.69)
    static let amber       = Color(red: 1.00, green: 0.78, blue: 0.32)
    static let danger      = Color(red: 0.97, green: 0.36, blue: 0.42)

    static let brandGradient = LinearGradient(
        colors: [brandStart, brandEnd],
        startPoint: .topLeading,
        endPoint: .bottomTrailing
    )

    static let softCard = LinearGradient(
        colors: [Color.white.opacity(0.04), Color.white.opacity(0.01)],
        startPoint: .top,
        endPoint: .bottom
    )

    static let cornerRadius: CGFloat = 14
    static let cardRadius:   CGFloat = 18
}

extension View {
    /// Translucent card with brand-tinted border + subtle gradient overlay.
    func odCard(padding: CGFloat = 18) -> some View {
        self
            .padding(padding)
            .background {
                RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous)
                    .fill(.background.opacity(0.6))
                    .overlay(
                        RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous)
                            .fill(Theme.softCard)
                    )
                    .overlay(
                        RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous)
                            .strokeBorder(Color.primary.opacity(0.06), lineWidth: 1)
                    )
                    .shadow(color: .black.opacity(0.06), radius: 18, y: 6)
            }
    }

    /// Brand-gradient pill button style.
    func odPrimaryButton() -> some View {
        self
            .font(.system(size: 13, weight: .semibold, design: .rounded))
            .foregroundStyle(.white)
            .padding(.horizontal, 14)
            .padding(.vertical, 9)
            .background(Capsule().fill(Theme.brandGradient))
            .overlay(Capsule().strokeBorder(Color.white.opacity(0.18), lineWidth: 0.5))
            .shadow(color: Theme.brandStart.opacity(0.35), radius: 10, y: 4)
    }

    func odSecondaryButton() -> some View {
        self
            .font(.system(size: 13, weight: .medium, design: .rounded))
            .foregroundStyle(.primary)
            .padding(.horizontal, 14)
            .padding(.vertical, 9)
            .background(Capsule().fill(Color.primary.opacity(0.06)))
            .overlay(Capsule().strokeBorder(Color.primary.opacity(0.08), lineWidth: 0.5))
    }
}

extension Array where Element: Hashable {
    func uniqued() -> [Element] {
        var seen = Set<Element>(); var result: [Element] = []
        for e in self where seen.insert(e).inserted { result.append(e) }
        return result
    }
}

struct SectionHeader: View {
    let title: String
    let subtitle: String?
    init(_ title: String, subtitle: String? = nil) {
        self.title = title; self.subtitle = subtitle
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title)
                .font(.system(size: 22, weight: .bold, design: .rounded))
            if let subtitle {
                Text(subtitle)
                    .font(.system(size: 13))
                    .foregroundStyle(.secondary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}
