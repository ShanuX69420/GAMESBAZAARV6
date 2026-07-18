'use client';

import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

// Lists at or past this size get a search box inside the menu.
const SEARCH_THRESHOLD = 12;

/*
 * Themed replacement for native <select>.
 * - options: [{ value, label }] — include the "All …" / placeholder row as a
 *   real option when it should be selectable, exactly like a native <option>.
 * - onChange receives the picked option's value directly, not an event.
 * - The menu renders in a portal with fixed positioning so it can never be
 *   clipped by overflow-hidden ancestors (mobile filter panel, edit modals),
 *   and flips upward when there is more room above than below.
 * - `required`/`name` render an invisible proxy input so native form
 *   validation still blocks submits with no selection.
 */
export default function Select({
  id,
  className = '',
  value,
  onChange,
  options,
  placeholder = 'Select...',
  ariaLabel,
  disabled = false,
  required = false,
  name,
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [highlighted, setHighlighted] = useState(0);
  const rootRef = useRef(null);
  const triggerRef = useRef(null);
  const menuRef = useRef(null);
  const listRef = useRef(null);
  const searchRef = useRef(null);
  const openUpRef = useRef(null);
  const typeahead = useRef({ q: '', at: 0 });
  const reactId = useId();
  const listboxId = `${id || reactId}-listbox`;

  const searchable = options.length >= SEARCH_THRESHOLD;
  const trimmedQuery = query.trim().toLowerCase();
  const filtered = trimmedQuery
    ? options.filter((o) => String(o.label).toLowerCase().includes(trimmedQuery))
    : options;
  const selectedIndex = options.findIndex((o) => String(o.value) === String(value));
  const selectedLabel = selectedIndex >= 0 ? options[selectedIndex].label : placeholder;
  const activeId = open && filtered[highlighted] ? `${listboxId}-opt-${highlighted}` : undefined;

  const close = useCallback((refocus) => {
    setOpen(false);
    setQuery('');
    if (refocus) triggerRef.current?.focus();
  }, []);

  const openMenu = () => {
    if (disabled) return;
    setQuery('');
    setHighlighted(selectedIndex >= 0 ? selectedIndex : 0);
    openUpRef.current = null;
    setOpen(true);
  };

  const setActive = (i) => {
    setHighlighted(i);
    listRef.current?.children[i]?.scrollIntoView({ block: 'nearest' });
  };

  const commit = (i) => {
    const opt = filtered[i];
    if (!opt) return;
    onChange(opt.value);
    close(true);
  };

  const typeaheadJump = (ch) => {
    const t = typeahead.current;
    const now = Date.now();
    if (now - t.at > 600) t.q = '';
    t.q += ch.toLowerCase();
    t.at = now;
    const start = t.q.length === 1 ? highlighted + 1 : highlighted;
    for (let k = 0; k < filtered.length; k++) {
      const i = (start + k) % filtered.length;
      if (String(filtered[i].label).toLowerCase().startsWith(t.q)) {
        setActive(i);
        return;
      }
    }
  };

  const onKeyDown = (e) => {
    if (!open) {
      if (e.key === 'Enter' || e.key === ' ' || e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        openMenu();
      } else if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
        openMenu();
      }
      return;
    }
    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        if (filtered.length) setActive(Math.min(highlighted + 1, filtered.length - 1));
        break;
      case 'ArrowUp':
        e.preventDefault();
        if (filtered.length) setActive(Math.max(highlighted - 1, 0));
        break;
      case 'Home':
        // In the search input Home/End must keep moving the caret.
        if (!searchable && filtered.length) {
          e.preventDefault();
          setActive(0);
        }
        break;
      case 'End':
        if (!searchable && filtered.length) {
          e.preventDefault();
          setActive(filtered.length - 1);
        }
        break;
      case 'Enter':
        e.preventDefault();
        commit(highlighted);
        break;
      case ' ':
        if (!searchable) {
          e.preventDefault();
          commit(highlighted);
        }
        break;
      case 'Escape':
        e.preventDefault();
        close(true);
        break;
      case 'Tab':
        e.preventDefault();
        close(true);
        break;
      default:
        if (!searchable && e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
          typeaheadJump(e.key);
        }
    }
  };

  // Close when clicking/tapping anywhere outside the trigger or the menu.
  useEffect(() => {
    if (!open) return undefined;
    const onPointerDown = (e) => {
      if (rootRef.current?.contains(e.target)) return;
      if (menuRef.current?.contains(e.target)) return;
      close(false);
    };
    document.addEventListener('pointerdown', onPointerDown, true);
    return () => document.removeEventListener('pointerdown', onPointerDown, true);
  }, [open, close]);

  useEffect(() => {
    if (!open || !searchable) return;
    // Auto-focusing the search box pops the on-screen keyboard on touch
    // devices, covering half the menu — there, wait for an explicit tap.
    if (window.matchMedia('(pointer: coarse)').matches) return;
    searchRef.current?.focus();
  }, [open, searchable]);

  // Position the portal menu against the trigger; re-run while scrolling or
  // resizing so it tracks the trigger, and when filtering changes its height.
  useLayoutEffect(() => {
    if (!open) return undefined;
    const position = () => {
      const trigger = triggerRef.current;
      const menu = menuRef.current;
      if (!trigger || !menu) return;
      const rect = trigger.getBoundingClientRect();
      if (rect.bottom < 0 || rect.top > window.innerHeight) {
        close(false);
        return;
      }
      menu.style.minWidth = `${rect.width}px`;
      menu.style.maxWidth = `${Math.min(360, window.innerWidth - 16)}px`;
      const gap = 6;
      const below = window.innerHeight - rect.bottom - gap - 8;
      const above = rect.top - gap - 8;
      // Lock the direction on open — re-deciding on every scroll tick makes
      // the menu flip sides mid-scroll when space above/below is near equal.
      if (openUpRef.current === null) {
        openUpRef.current = Math.min(340, menu.offsetHeight) > below && above > below;
      }
      const openUp = openUpRef.current;
      menu.style.maxHeight = `${Math.max(120, Math.min(340, openUp ? above : below))}px`;
      menu.style.top = openUp
        ? `${Math.max(8, rect.top - gap - menu.offsetHeight)}px`
        : `${rect.bottom + gap}px`;
      let left = rect.left;
      if (left + menu.offsetWidth > window.innerWidth - 8) {
        left = Math.max(8, window.innerWidth - 8 - menu.offsetWidth);
      }
      menu.style.left = `${left}px`;
      menu.classList.toggle('gb-select-menu-up', openUp);
      menu.style.visibility = 'visible';
    };
    position();
    listRef.current?.children[highlighted]?.scrollIntoView({ block: 'nearest' });
    window.addEventListener('resize', position);
    window.addEventListener('scroll', position, true);
    return () => {
      window.removeEventListener('resize', position);
      window.removeEventListener('scroll', position, true);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, filtered.length]);

  return (
    <div className={`gb-select${className ? ` ${className}` : ''}`} ref={rootRef}>
      <button
        type="button"
        id={id}
        ref={triggerRef}
        className={`gb-select-trigger${open ? ' gb-select-trigger-open' : ''}`}
        onClick={() => (open ? close(true) : openMenu())}
        onKeyDown={onKeyDown}
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listboxId : undefined}
        aria-label={ariaLabel}
        aria-activedescendant={searchable ? undefined : activeId}
      >
        <span className={`gb-select-value${selectedIndex < 0 ? ' gb-select-placeholder' : ''}`}>
          {selectedLabel}
        </span>
        <svg className="gb-select-chevron" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>
      {(required || name) && (
        <input
          className="gb-select-native-proxy"
          type="text"
          tabIndex={-1}
          aria-hidden="true"
          name={name}
          value={value == null ? '' : String(value)}
          onChange={() => {}}
          required={required}
        />
      )}
      {open && createPortal(
        <div className="gb-select-menu" ref={menuRef}>
          {searchable && (
            <div className="gb-select-search">
              <svg className="gb-select-search-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <circle cx="11" cy="11" r="8" />
                <line x1="21" y1="21" x2="16.65" y2="16.65" />
              </svg>
              <input
                ref={searchRef}
                className="gb-select-search-input"
                type="text"
                value={query}
                placeholder="Search..."
                onChange={(e) => {
                  setQuery(e.target.value);
                  setHighlighted(0);
                }}
                onKeyDown={onKeyDown}
                role="combobox"
                aria-expanded="true"
                aria-controls={listboxId}
                aria-activedescendant={activeId}
                aria-autocomplete="list"
              />
            </div>
          )}
          <ul className="gb-select-list" id={listboxId} role="listbox" ref={listRef} aria-label={ariaLabel}>
            {filtered.length === 0 ? (
              <li className="gb-select-empty" role="presentation">No matches</li>
            ) : (
              filtered.map((opt, i) => {
                const isSelected = String(opt.value) === String(value);
                return (
                  <li
                    key={`${opt.value}-${i}`}
                    id={`${listboxId}-opt-${i}`}
                    role="option"
                    aria-selected={isSelected}
                    className={`gb-select-option${i === highlighted ? ' gb-select-option-active' : ''}${isSelected ? ' gb-select-option-selected' : ''}`}
                    onPointerDown={(e) => e.preventDefault()}
                    onClick={() => commit(i)}
                    onMouseEnter={() => setHighlighted(i)}
                  >
                    <span className="gb-select-option-label">{opt.label}</span>
                    {isSelected && (
                      <svg className="gb-select-check" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                        <polyline points="20 6 9 17 4 12" />
                      </svg>
                    )}
                  </li>
                );
              })
            )}
          </ul>
        </div>,
        document.body
      )}
    </div>
  );
}
