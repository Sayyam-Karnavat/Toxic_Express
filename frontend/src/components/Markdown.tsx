import ReactMarkdown from "react-markdown";

const ALLOWED = ["p", "strong", "em", "del", "ul", "ol", "li", "a", "code", "blockquote", "br"];

/** Markdown-lite renderer. Raw HTML is never rendered and unsafe URLs are stripped. */
export function Markdown({ children, className }: { children: string; className?: string }) {
  return (
    <div className={className}>
      <ReactMarkdown
        allowedElements={ALLOWED}
        unwrapDisallowed
        skipHtml
        components={{
          a: ({ href, children: text }) => (
            <a href={href} target="_blank" rel="noopener noreferrer nofollow ugc" className="text-link-cyan underline">
              {text}
            </a>
          ),
          p: ({ children: text }) => <p className="mb-sm whitespace-pre-line last:mb-0">{text}</p>,
          ul: ({ children: items }) => <ul className="mb-sm list-disc pl-xl">{items}</ul>,
          ol: ({ children: items }) => <ol className="mb-sm list-decimal pl-xl">{items}</ol>,
          blockquote: ({ children: q }) => (
            <blockquote className="mb-sm border-l-4 border-primary pl-md text-ink-soft">{q}</blockquote>
          ),
          code: ({ children: c }) => <code className="rounded-xs bg-canvas px-xxs py-0.5 text-link-sm">{c}</code>,
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
