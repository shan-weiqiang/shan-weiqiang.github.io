# frozen_string_literal: true

module Jekyll
  module TableScrollWrapper
    module_function

    def wrap(html)
      return html unless html&.include?("<table")

      html
        .gsub(/<table(\s[^>]*)?>/, '<div class="table-scroll"><table\1>')
        .gsub("</table>", "</table></div>")
    end
  end
end

# Wrap at post_convert (post body HTML, before layout). Register :documents only
# for collection items — trigger_hooks also fires :documents for posts, so do not
# also register :posts or tables get wrapped twice.
Jekyll::Hooks.register :documents, :post_convert do |doc|
  doc.content = Jekyll::TableScrollWrapper.wrap(doc.content)
end

Jekyll::Hooks.register :pages, :post_convert do |doc|
  doc.content = Jekyll::TableScrollWrapper.wrap(doc.content)
end
